// Definitions for the device internals declared in kivo.h: serial line I/O,
// frame helpers, the LCD driver, the sensor manager + registry, and command
// dispatch + handlers. The Arduino-independent framing/CRC lives in
// lib/kivo_protocol so it can be host-unit-tested.

#include "kivo.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "config.h"


// -- SerialLine --------------------------------------------------------------

void SerialLine::begin(unsigned long baud) { Serial.begin(baud); }

char* SerialLine::poll() {
  while (Serial.available() > 0) {
    char c = static_cast<char>(Serial.read());
    if (c == '\r') {
      continue;  // tolerate CRLF line endings
    }
    if (c == '\n') {
      if (overflow_) {
        // The line was too long and was discarded; surface it as overflow so
        // the caller can emit a malformed-frame event, then reset.
        overflow_ = false;
        overflowLatched_ = true;
        length_ = 0;
        return nullptr;
      }
      buffer_[length_] = '\0';
      length_ = 0;
      return buffer_;
    }
    if (length_ < kivo::KIVO_LINE_MAX) {
      buffer_[length_++] = c;
    } else {
      overflow_ = true;  // keep consuming until newline, then discard
    }
  }
  return nullptr;
}

bool SerialLine::takeOverflow() {
  bool latched = overflowLatched_;
  overflowLatched_ = false;
  return latched;
}

void SerialLine::sendLine(const char* line) {
  Serial.print(line);
  Serial.print('\n');
}

int SerialLine::availableForWrite() { return Serial.availableForWrite(); }


// -- ProtocolIO --------------------------------------------------------------

// Frame type tokens and the reserved event id (see /protocol/README.md §4-5).
static const char* const kTypeRes = "RES";
static const char* const kTypeEvt = "EVT";
static const uint16_t kEventId = 0;

void ProtocolIO::sendOk(uint16_t id, const char* data) {
  char body[kivo::KIVO_LINE_MAX];
  if (data != nullptr && data[0] != '\0') {
    snprintf(body, sizeof(body), "%s %s", KIVO_STATUS_OK, data);
  } else {
    snprintf(body, sizeof(body), "%s", KIVO_STATUS_OK);
  }
  sendFrame(kTypeRes, id, body);
}

void ProtocolIO::sendError(uint16_t id, uint8_t code, const char* message) {
  char body[kivo::KIVO_LINE_MAX];
  snprintf(body, sizeof(body), "%s %u %s", KIVO_STATUS_ERR,
           static_cast<unsigned>(code), message);
  sendFrame(kTypeRes, id, body);
}

void ProtocolIO::sendEvent(const char* name, const char* data) {
  char body[kivo::KIVO_LINE_MAX];
  if (data != nullptr && data[0] != '\0') {
    snprintf(body, sizeof(body), "%s %s", name, data);
  } else {
    snprintf(body, sizeof(body), "%s", name);
  }
  sendFrame(kTypeEvt, kEventId, body);
}

void ProtocolIO::sendErrorEvent(uint8_t code, const char* message) {
  char data[kivo::KIVO_LINE_MAX];
  snprintf(data, sizeof(data), "%u %s", static_cast<unsigned>(code), message);
  sendEvent(KIVO_EVT_ERROR, data);
}

bool ProtocolIO::trySendEvent(const char* name, const char* data) {
  char body[kivo::KIVO_LINE_MAX];
  if (data != nullptr && data[0] != '\0') {
    snprintf(body, sizeof(body), "%s %s", name, data);
  } else {
    snprintf(body, sizeof(body), "%s", name);
  }
  char line[kivo::KIVO_LINE_MAX + 1];
  int n = kivo::format_frame(line, sizeof(line), kTypeEvt, kEventId, body);
  if (n <= 0) {
    return false;
  }
  // +1 for the newline sendLine appends. If it would not fit, drop the sample.
  if (line_.availableForWrite() < n + 1) {
    return false;
  }
  line_.sendLine(line);
  return true;
}

void ProtocolIO::sendFrame(const char* type, uint16_t id, const char* body) {
  char line[kivo::KIVO_LINE_MAX + 1];
  int n = kivo::format_frame(line, sizeof(line), type, id, body);
  if (n > 0) {
    line_.sendLine(line);
  }
  // If formatting overflowed the line budget there is nothing safe to send;
  // dropping it beats emitting a truncated, mis-checksummed frame.
}


// -- LcdDisplay --------------------------------------------------------------

LcdDisplay::LcdDisplay(uint8_t rs, uint8_t en, uint8_t d4, uint8_t d5, uint8_t d6,
                       uint8_t d7, uint8_t cols, uint8_t rows)
    : lcd_(rs, en, d4, d5, d6, d7), cols_(cols), rows_(rows) {}

void LcdDisplay::begin() { lcd_.begin(cols_, rows_); }

void LcdDisplay::clear() { lcd_.clear(); }

bool LcdDisplay::write(uint8_t row, uint8_t col, const char* text) {
  if (row >= rows_ || col >= cols_) {
    return false;
  }
  lcd_.setCursor(col, row);
  // Print only what fits between col and the right edge, so text never spills
  // into off-screen DDRAM or the next line.
  uint8_t budget = cols_ - col;
  for (uint8_t i = 0; i < budget && text[i] != '\0'; ++i) {
    lcd_.write(text[i]);
  }
  return true;
}


// -- SensorManager -----------------------------------------------------------

SensorManager::SensorManager(SensorEntry* entries, size_t count, ProtocolIO& io,
                             unsigned long sampleMs)
    : entries_(entries),
      count_(count),
      io_(io),
      sampleMs_(sampleMs),
      lastSample_(0) {}

void SensorManager::begin() {
  for (size_t i = 0; i < count_; ++i) {
    entries_[i].sensor->begin();
  }
}

SensorEntry* SensorManager::find(const char* name) {
  for (size_t i = 0; i < count_; ++i) {
    if (strcmp(name, entries_[i].sensor->name()) == 0) {
      return &entries_[i];
    }
  }
  return nullptr;
}

bool SensorManager::subscribe(const char* name) {
  SensorEntry* entry = find(name);
  if (entry == nullptr) {
    return false;
  }
  entry->subscribed = true;
  entry->primed = false;  // force an initial reading on the next poll
  return true;
}

bool SensorManager::unsubscribe(const char* name) {
  SensorEntry* entry = find(name);
  if (entry == nullptr) {
    return false;
  }
  entry->subscribed = false;
  return true;
}

bool SensorManager::read(const char* name, int& valueOut) {
  SensorEntry* entry = find(name);
  if (entry == nullptr) {
    return false;
  }
  valueOut = entry->sensor->read();
  return true;
}

void SensorManager::poll(unsigned long now) {
  // Advance every sensor's own state machine each loop iteration (e.g. the
  // ultrasonic echo timing), independent of the slower emission cadence below.
  for (size_t i = 0; i < count_; ++i) {
    entries_[i].sensor->update();
  }

  // Unsigned subtraction handles millis() rollover correctly.
  if (now - lastSample_ < sampleMs_) {
    return;
  }
  lastSample_ = now;

  for (size_t i = 0; i < count_; ++i) {
    SensorEntry& entry = entries_[i];
    if (!entry.subscribed) {
      continue;
    }
    int value = entry.sensor->read();
    int delta = value - entry.lastValue;
    if (delta < 0) {
      delta = -delta;
    }
    if (entry.primed && delta < entry.sensor->changeThreshold()) {
      continue;  // not enough change to be worth reporting
    }
    char data[kivo::KIVO_LINE_MAX];
    snprintf(data, sizeof(data), "%s %d", entry.sensor->name(), value);
    // Only commit the new baseline if the sample actually went out; otherwise
    // retry on the next cadence rather than silently swallowing the change.
    if (io_.trySendEvent(KIVO_EVT_SENSOR, data)) {
      entry.lastValue = value;
      entry.primed = true;
    }
  }
}


// -- sensor registry (the single place sensors are declared) -----------------

static AnalogSensor lightSensor("light", KIVO_SENSOR_LIGHT_PIN,
                                KIVO_SENSOR_LIGHT_CHANGE);
static DigitalSensor presenceSensor("presence", KIVO_SENSOR_PRESENCE_PIN);
static UltrasonicSensor distanceSensor("distance", KIVO_SENSOR_DISTANCE_TRIG_PIN,
                                       KIVO_SENSOR_DISTANCE_ECHO_PIN,
                                       KIVO_SENSOR_DISTANCE_CHANGE);

SensorEntry KIVO_SENSORS[] = {
    {&lightSensor, /*subscribed=*/false, /*lastValue=*/0, /*primed=*/false},
    {&presenceSensor, /*subscribed=*/false, /*lastValue=*/0, /*primed=*/false},
    {&distanceSensor, /*subscribed=*/false, /*lastValue=*/0, /*primed=*/false},
};

const size_t KIVO_SENSOR_COUNT = sizeof(KIVO_SENSORS) / sizeof(KIVO_SENSORS[0]);


// -- Dispatcher --------------------------------------------------------------

void Dispatcher::handleLine(char* line) {
  kivo::ParsedFrame frame;
  kivo::ParseError err = kivo::parse_frame(line, frame);
  if (err == kivo::ParseError::CRC_FAIL) {
    ctx_.io.sendErrorEvent(KIVO_ERR_CRC_FAIL, KIVO_ERRMSG_CRC_FAIL);
    return;
  }
  if (err == kivo::ParseError::MALFORMED) {
    ctx_.io.sendErrorEvent(KIVO_ERR_MALFORMED, KIVO_ERRMSG_MALFORMED);
    return;
  }

  // The device only acts on commands; it ignores stray RES/EVT frames.
  if (frame.type != kivo::FrameType::CMD) {
    return;
  }

  // Split the body into "op" and "args". body points into the mutable line
  // buffer, so we can terminate the op in place.
  char* op = const_cast<char*>(frame.body);
  char* args = const_cast<char*>("");
  char* space = strchr(op, ' ');
  if (space != nullptr) {
    *space = '\0';
    args = space + 1;
  }

  for (size_t i = 0; i < KIVO_HANDLER_COUNT; ++i) {
    if (strcmp(op, KIVO_HANDLERS[i].op) == 0) {
      KIVO_HANDLERS[i].fn(ctx_, frame.id, args);
      return;
    }
  }
  ctx_.io.sendError(frame.id, KIVO_ERR_UNKNOWN_OP, KIVO_ERRMSG_UNKNOWN_OP);
}


// -- handlers ----------------------------------------------------------------

void handlePing(DeviceContext& ctx, uint16_t id, const char* args) {
  (void)args;
  ctx.io.sendOk(id, KIVO_PAYLOAD_PONG);
}

void handleIdentify(DeviceContext& ctx, uint16_t id, const char* args) {
  (void)args;
  char identity[kivo::KIVO_LINE_MAX];
  snprintf(identity, sizeof(identity), "%s %s %s", KIVO_FW_NAME, KIVO_FW_VERSION,
           KIVO_PROTO_VERSION);
  ctx.io.sendOk(id, identity);
}

// Parse "<row> <col> <text>". On success writes row/col/text and returns true.
// `args` is not modified; `text` points into it.
static bool parseWriteArgs(const char* args, long& row, long& col,
                           const char*& text) {
  char* end = nullptr;
  row = strtol(args, &end, 10);
  if (end == args || *end != ' ') return false;

  const char* after_row = end + 1;
  col = strtol(after_row, &end, 10);
  if (end == after_row) return false;

  if (*end == ' ') {
    text = end + 1;
  } else if (*end == '\0') {
    text = "";  // positioning with no text is a valid no-op write
  } else {
    return false;  // trailing garbage where a space or end was expected
  }
  return true;
}

void handleDisplayWrite(DeviceContext& ctx, uint16_t id, const char* args) {
  long row = 0;
  long col = 0;
  const char* text = "";
  if (!parseWriteArgs(args, row, col, text) || row < 0 || col < 0) {
    ctx.io.sendError(id, KIVO_ERR_BAD_ARGS, KIVO_ERRMSG_BAD_ARGS);
    return;
  }
  // The driver bounds-checks against the actual geometry and reports if the
  // cell is off-screen; the host never needs to know the dimensions.
  if (!ctx.display.write(static_cast<uint8_t>(row), static_cast<uint8_t>(col),
                         text)) {
    ctx.io.sendError(id, KIVO_ERR_BAD_ARGS, KIVO_ERRMSG_BAD_ARGS);
    return;
  }
  ctx.io.sendOk(id);
}

void handleDisplayClear(DeviceContext& ctx, uint16_t id, const char* args) {
  (void)args;
  ctx.display.clear();
  ctx.io.sendOk(id);
}

void handleSensorRead(DeviceContext& ctx, uint16_t id, const char* args) {
  int value = 0;
  if (!ctx.sensors.read(args, value)) {
    ctx.io.sendError(id, KIVO_ERR_BAD_ARGS, KIVO_ERRMSG_BAD_ARGS);
    return;
  }
  char buf[12];
  snprintf(buf, sizeof(buf), "%d", value);
  ctx.io.sendOk(id, buf);
}

void handleSensorSubscribe(DeviceContext& ctx, uint16_t id, const char* args) {
  if (!ctx.sensors.subscribe(args)) {
    ctx.io.sendError(id, KIVO_ERR_BAD_ARGS, KIVO_ERRMSG_BAD_ARGS);
    return;
  }
  ctx.io.sendOk(id);
}

void handleSensorUnsubscribe(DeviceContext& ctx, uint16_t id, const char* args) {
  if (!ctx.sensors.unsubscribe(args)) {
    ctx.io.sendError(id, KIVO_ERR_BAD_ARGS, KIVO_ERRMSG_BAD_ARGS);
    return;
  }
  ctx.io.sendOk(id);
}

// -- expressions -------------------------------------------------------------

// Parse a single 0/1 field at *p, advancing *p past it. Returns false on junk.
static bool parseBit(const char*& p, uint8_t& out) {
  if (*p != '0' && *p != '1') return false;
  out = static_cast<uint8_t>(*p - '0');
  ++p;
  return true;
}

void handleLedSet(DeviceContext& ctx, uint16_t id, const char* args) {
  // "r g b", each 0 or 1.
  const char* p = args;
  uint8_t r = 0, g = 0, b = 0;
  if (!parseBit(p, r) || *p++ != ' ' || !parseBit(p, g) || *p++ != ' ' ||
      !parseBit(p, b) || *p != '\0') {
    ctx.io.sendError(id, KIVO_ERR_BAD_ARGS, KIVO_ERRMSG_BAD_ARGS);
    return;
  }
  ctx.led.set(r, g, b);
  ctx.io.sendOk(id);
}

void handleTonePlay(DeviceContext& ctx, uint16_t id, const char* args) {
  // "freq ms" — freq 0 silences.
  char* end = nullptr;
  long freq = strtol(args, &end, 10);
  if (end == args || *end != ' ' || freq < 0) {
    ctx.io.sendError(id, KIVO_ERR_BAD_ARGS, KIVO_ERRMSG_BAD_ARGS);
    return;
  }
  const char* ms_str = end + 1;
  long ms = strtol(ms_str, &end, 10);
  if (end == ms_str || *end != '\0' || ms < 0) {
    ctx.io.sendError(id, KIVO_ERR_BAD_ARGS, KIVO_ERRMSG_BAD_ARGS);
    return;
  }
  ctx.buzzer.play(static_cast<unsigned int>(freq), static_cast<unsigned long>(ms));
  ctx.io.sendOk(id);
}

// Operation names are matched exactly (uppercase by convention). This table is
// the single source of registered capabilities.
const CommandHandler KIVO_HANDLERS[] = {
    {"PING", handlePing},
    {"SYS.IDENTIFY", handleIdentify},
    {"DISPLAY.WRITE", handleDisplayWrite},
    {"DISPLAY.CLEAR", handleDisplayClear},
    {"SENSOR.READ", handleSensorRead},
    {"SENSOR.SUBSCRIBE", handleSensorSubscribe},
    {"SENSOR.UNSUBSCRIBE", handleSensorUnsubscribe},
    {"LED.SET", handleLedSet},
    {"TONE.PLAY", handleTonePlay},
};

const size_t KIVO_HANDLER_COUNT = sizeof(KIVO_HANDLERS) / sizeof(KIVO_HANDLERS[0]);
