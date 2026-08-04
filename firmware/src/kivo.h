// Kivo device internals: serial line I/O, outgoing-frame helpers, the LCD
// driver, the sensor hierarchy + manager, and command dispatch/handlers.
//
// One header for the whole device (the project is small); definitions live in
// kivo.cpp. The Arduino-independent framing/CRC stays in lib/kivo_protocol so it
// can be host-unit-tested. Wiring and geometry come from config.h, injected via
// constructors, so hardware details live in exactly one place.

#ifndef KIVO_H
#define KIVO_H

#include <Arduino.h>
#include <LiquidCrystal.h>
#include <Servo.h>
#include <stddef.h>
#include <stdint.h>

#include "kivo_protocol.h"  // KIVO_LINE_MAX, ParsedFrame, parse/format


// -- SerialLine: non-blocking, line-oriented reader/writer -------------------

class SerialLine {
 public:
  void begin(unsigned long baud);

  // A NUL-terminated completed line (without terminator), or nullptr if none is
  // ready. Valid until the next poll(). Never blocks.
  char* poll();

  // True once if the most recent line overflowed and was discarded; clears the
  // flag. Lets the caller report a malformed frame.
  bool takeOverflow();

  void sendLine(const char* line);

  // Free space (bytes) in the outgoing serial buffer, so callers can avoid a
  // blocking write when the host isn't draining the link (streaming).
  int availableForWrite();

 private:
  char buffer_[kivo::KIVO_LINE_MAX + 1];
  uint8_t length_ = 0;
  bool overflow_ = false;
  bool overflowLatched_ = false;
};


// -- ProtocolIO: build + send well-formed RES / EVT frames -------------------

class ProtocolIO {
 public:
  explicit ProtocolIO(SerialLine& line) : line_(line) {}

  void sendOk(uint16_t id, const char* data = nullptr);         // RES id OK [data]
  void sendError(uint16_t id, uint8_t code, const char* message);  // RES id ERR ...
  void sendEvent(const char* name, const char* data = nullptr);    // EVT 0 name [data]
  void sendErrorEvent(uint8_t code, const char* message);       // EVT 0 ERROR ...

  // Like sendEvent, but never blocks: if the outgoing buffer lacks room for the
  // whole frame the event is dropped and false is returned (for streaming).
  bool trySendEvent(const char* name, const char* data);

 private:
  void sendFrame(const char* type, uint16_t id, const char* body);
  SerialLine& line_;
};


// -- LcdDisplay: a narrow capability over the LiquidCrystal library -----------

class LcdDisplay {
 public:
  LcdDisplay(uint8_t rs, uint8_t en, uint8_t d4, uint8_t d5, uint8_t d6,
             uint8_t d7, uint8_t cols, uint8_t rows);

  void begin();  // call once from setup()
  void clear();

  // Write text starting at (row, col), truncated at the row's right edge.
  // Returns false (writing nothing) if row/col are out of range.
  bool write(uint8_t row, uint8_t col, const char* text);

  uint8_t cols() const { return cols_; }
  uint8_t rows() const { return rows_; }

 private:
  LiquidCrystal lcd_;
  uint8_t cols_;
  uint8_t rows_;
};


// -- Sensors: a small polymorphic hierarchy (header-only) ---------------------

// A readable sensor, addressed by name and producing a raw integer reading.
class Sensor {
 public:
  Sensor(const char* name, int changeThreshold)
      : name_(name), changeThreshold_(changeThreshold) {}
  virtual ~Sensor() {}

  // One-time pin setup at boot. Default: nothing (analog inputs need none).
  virtual void begin() {}

  // Called every loop iteration. Simple sensors read on demand and need nothing
  // here; a sensor whose measurement takes time (ultrasonic echo) uses this to
  // advance its non-blocking state machine. Default: nothing.
  virtual void update() {}

  // Raw reading in device units (interpretation is the host's job).
  virtual int read() = 0;

  const char* name() const { return name_; }

  // Smallest change worth streaming, in this sensor's own units - analog needs a
  // margin above its noise floor; a digital 0<->1 flip (delta 1) always matters.
  int changeThreshold() const { return changeThreshold_; }

 private:
  const char* name_;
  int changeThreshold_;
};

// Analog input pin (e.g. a photoresistor divider).
class AnalogSensor : public Sensor {
 public:
  AnalogSensor(const char* name, uint8_t pin, int changeThreshold)
      : Sensor(name, changeThreshold), pin_(pin) {}
  int read() override { return analogRead(pin_); }

 private:
  uint8_t pin_;
};

// Digital input pin (e.g. a PIR motion sensor). Reads 0/1; any flip matters.
class DigitalSensor : public Sensor {
 public:
  DigitalSensor(const char* name, uint8_t pin)
      : Sensor(name, /*changeThreshold=*/1), pin_(pin) {}
  void begin() override { pinMode(pin_, INPUT); }
  int read() override { return digitalRead(pin_); }

 private:
  uint8_t pin_;
};

// HC-SR04 ultrasonic range finder, reporting distance (cm) to the nearest
// object. The echo pulse lasts up to tens of ms, so update() runs a state
// machine that fires the trigger then polls the echo across loop iterations
// (never blocking); read() returns the last completed measurement.
class UltrasonicSensor : public Sensor {
 public:
  UltrasonicSensor(const char* name, uint8_t trigPin, uint8_t echoPin,
                   int changeThreshold, int maxCm = 400,
                   unsigned long intervalMs = 60)
      : Sensor(name, changeThreshold),
        trigPin_(trigPin),
        echoPin_(echoPin),
        maxCm_(maxCm),
        intervalMs_(intervalMs),
        state_(IDLE),
        distanceCm_(maxCm),
        lastMeasureMs_(0),
        echoStartUs_(0),
        waitStartUs_(0) {}

  void begin() override {
    pinMode(trigPin_, OUTPUT);
    digitalWrite(trigPin_, LOW);
    pinMode(echoPin_, INPUT);
  }

  int read() override { return distanceCm_; }

  void update() override {
    switch (state_) {
      case IDLE:
        // Space measurements out so a returning echo can't collide with the
        // next ping (the HC-SR04 needs a short gap between readings).
        if (millis() - lastMeasureMs_ >= intervalMs_) {
          // A 10us trigger pulse: far too short to matter to the loop.
          digitalWrite(trigPin_, HIGH);
          delayMicroseconds(10);
          digitalWrite(trigPin_, LOW);
          waitStartUs_ = micros();
          state_ = WAIT_RISING;
        }
        break;
      case WAIT_RISING:
        if (digitalRead(echoPin_) == HIGH) {
          echoStartUs_ = micros();
          state_ = WAIT_FALLING;
        } else if (micros() - waitStartUs_ > kRisingTimeoutUs) {
          finish(maxCm_);  // no echo began -> nothing within range
        }
        break;
      case WAIT_FALLING:
        if (digitalRead(echoPin_) == LOW) {
          unsigned long echoUs = micros() - echoStartUs_;
          long cm = static_cast<long>(echoUs / 58);  // ~58us per cm, round trip
          finish(cm > maxCm_ ? maxCm_ : static_cast<int>(cm));
        } else if (micros() - echoStartUs_ > kEchoTimeoutUs) {
          finish(maxCm_);  // echo overran -> out of range
        }
        break;
    }
  }

 private:
  enum State { IDLE, WAIT_RISING, WAIT_FALLING };
  static const unsigned long kRisingTimeoutUs = 5000;   // echo should start fast
  static const unsigned long kEchoTimeoutUs = 25000;    // ~430 cm ceiling

  void finish(int cm) {
    distanceCm_ = cm;
    lastMeasureMs_ = millis();
    state_ = IDLE;
  }

  uint8_t trigPin_;
  uint8_t echoPin_;
  int maxCm_;
  unsigned long intervalMs_;
  State state_;
  int distanceCm_;
  unsigned long lastMeasureMs_;
  unsigned long echoStartUs_;
  unsigned long waitStartUs_;
};


// -- RgbLed: digital-colour mood LED (header-only) ---------------------------

// Each channel is on/off (the Uno's PWM pins are taken), giving 7 primaries.
// `activeLow` inverts the levels for a common-anode LED.
class RgbLed {
 public:
  RgbLed(uint8_t rPin, uint8_t gPin, uint8_t bPin, bool activeLow)
      : rPin_(rPin), gPin_(gPin), bPin_(bPin), activeLow_(activeLow) {}

  void begin() {
    pinMode(rPin_, OUTPUT);
    pinMode(gPin_, OUTPUT);
    pinMode(bPin_, OUTPUT);
    set(0, 0, 0);
  }

  void set(uint8_t r, uint8_t g, uint8_t b) {
    digitalWrite(rPin_, level(r));
    digitalWrite(gPin_, level(g));
    digitalWrite(bPin_, level(b));
  }

 private:
  uint8_t level(uint8_t on) const {
    bool high = on != 0;
    if (activeLow_) high = !high;
    return high ? HIGH : LOW;
  }

  uint8_t rPin_;
  uint8_t gPin_;
  uint8_t bPin_;
  bool activeLow_;
};


// -- Buzzer: non-blocking chirps via tone() (header-only) ---------------------

class Buzzer {
 public:
  explicit Buzzer(uint8_t pin) : pin_(pin) {}
  void begin() { pinMode(pin_, OUTPUT); }

  // Play `freq` Hz for `ms` (tone() returns immediately; the tone stops itself).
  // freq 0 silences any current tone.
  void play(unsigned int freq, unsigned long ms) {
    if (freq == 0) {
      noTone(pin_);
    } else {
      tone(pin_, freq, ms);
    }
  }

 private:
  uint8_t pin_;
};


// -- ServoArm: Kivo's body language via a hobby servo (header-only) -----------

// The host sequences gestures from a series of setAngle() calls; the servo just
// holds the most recent angle. write() returns immediately (the servo moves at
// its own speed), so nothing here blocks the loop.
class ServoArm {
 public:
  explicit ServoArm(uint8_t pin) : pin_(pin) {}
  void begin() {
    servo_.attach(pin_);
    servo_.write(90);  // start centred, "looking at you"
  }
  void setAngle(uint8_t angle) { servo_.write(angle); }

 private:
  uint8_t pin_;
  Servo servo_;
};


// -- Button: debounced push button, streamed as a sensor event ---------------

// Polled every loop (so short taps aren't missed) with INPUT_PULLUP debounce.
// On a debounced press/release it emits `SENSOR button 1|0`; the host turns the
// timing into tap / double-tap / hold gestures. Defined in kivo.cpp (it needs the
// event-name macro from config.h).
class Button {
 public:
  Button(uint8_t pin, ProtocolIO& io) : pin_(pin), io_(io) {}
  void begin();
  void poll(unsigned long now);

 private:
  uint8_t pin_;
  ProtocolIO& io_;
  bool lastRaw_ = false;
  bool stable_ = false;
  unsigned long lastChange_ = 0;
};


// -- SensorManager: registry, subscriptions, and periodic streaming -----------

// A sensor plus its per-connection streaming state. `primed` becomes true once
// an initial reading has been emitted, so a fresh subscription always streams
// its current value before change-detection kicks in.
struct SensorEntry {
  Sensor* sensor;
  bool subscribed;
  int lastValue;
  bool primed;
};

class SensorManager {
 public:
  SensorManager(SensorEntry* entries, size_t count, ProtocolIO& io,
                unsigned long sampleMs);

  void begin();  // one-time pin setup for every registered sensor

  bool subscribe(const char* name);    // false if the name is unknown
  bool unsubscribe(const char* name);
  bool read(const char* name, int& valueOut);

  // Call every loop iteration with millis(); services sensors + samples on its
  // own cadence.
  void poll(unsigned long now);

 private:
  SensorEntry* find(const char* name);

  SensorEntry* entries_;
  size_t count_;
  ProtocolIO& io_;
  unsigned long sampleMs_;
  unsigned long lastSample_;
};

// The device's sensor registry - the single place sensors are declared (kivo.cpp).
extern SensorEntry KIVO_SENSORS[];
extern const size_t KIVO_SENSOR_COUNT;


// -- Command dispatch --------------------------------------------------------

// Services a handler may use: a plain struct of references (not a global grab-
// bag), so handlers stay decoupled from how the device is assembled in main.
struct DeviceContext {
  ProtocolIO& io;
  LcdDisplay& display;
  SensorManager& sensors;
  RgbLed& led;
  Buzzer& buzzer;
  ServoArm& servo;
};

// A handler receives the device services, the correlation id, and the argument
// string (everything after the operation name; empty if none).
typedef void (*HandlerFn)(DeviceContext& ctx, uint16_t id, const char* args);

struct CommandHandler {
  const char* op;
  HandlerFn fn;
};

// Routes a parsed command to the handler registered for its operation name.
class Dispatcher {
 public:
  Dispatcher(DeviceContext& ctx, const CommandHandler* handlers, size_t count)
      : ctx_(ctx), handlers_(handlers), count_(count) {}

  void handleLine(char* line);  // parse + act on one raw line (mutated in place)

 private:
  DeviceContext& ctx_;
  const CommandHandler* handlers_;
  size_t count_;
};

// Handlers (defined in kivo.cpp) and the registry the dispatcher iterates over.
void handlePing(DeviceContext& ctx, uint16_t id, const char* args);
void handleIdentify(DeviceContext& ctx, uint16_t id, const char* args);
void handleDisplayWrite(DeviceContext& ctx, uint16_t id, const char* args);
void handleDisplayClear(DeviceContext& ctx, uint16_t id, const char* args);
void handleSensorRead(DeviceContext& ctx, uint16_t id, const char* args);
void handleSensorSubscribe(DeviceContext& ctx, uint16_t id, const char* args);
void handleSensorUnsubscribe(DeviceContext& ctx, uint16_t id, const char* args);
void handleLedSet(DeviceContext& ctx, uint16_t id, const char* args);
void handleTonePlay(DeviceContext& ctx, uint16_t id, const char* args);
void handleServoSet(DeviceContext& ctx, uint16_t id, const char* args);

extern const CommandHandler KIVO_HANDLERS[];
extern const size_t KIVO_HANDLER_COUNT;

#endif  // KIVO_H
