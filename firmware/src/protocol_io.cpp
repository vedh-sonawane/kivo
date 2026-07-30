#include "protocol_io.h"

#include <stdio.h>

#include "kivo_protocol.h"
#include "protocol_vocab.h"

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

void ProtocolIO::sendFrame(const char* type, uint16_t id, const char* body) {
  char line[kivo::KIVO_LINE_MAX + 1];
  int n = kivo::format_frame(line, sizeof(line), type, id, body);
  if (n > 0) {
    line_.sendLine(line);
  }
  // If formatting overflowed the line budget there is nothing safe to send;
  // dropping it is preferable to emitting a truncated, mis-checksummed frame.
}
