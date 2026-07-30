// Outgoing-message helpers: build well-formed RES / EVT frames and send them.
//
// Handlers depend on this small interface rather than on the serial transport
// or the frame format directly, so response construction lives in exactly one
// place.

#ifndef KIVO_PROTOCOL_IO_H
#define KIVO_PROTOCOL_IO_H

#include <stdint.h>

#include "serial_line.h"

class ProtocolIO {
 public:
  explicit ProtocolIO(SerialLine& line) : line_(line) {}

  // RES <id> OK [data]
  void sendOk(uint16_t id, const char* data = nullptr);

  // RES <id> ERR <code> <message>
  void sendError(uint16_t id, uint8_t code, const char* message);

  // EVT 0 <name> [data]
  void sendEvent(const char* name, const char* data = nullptr);

  // EVT 0 ERROR <code> <message> — a frame-level failure (see spec §8).
  // Centralizes construction of error events so the format lives in one place.
  void sendErrorEvent(uint8_t code, const char* message);

 private:
  void sendFrame(const char* type, uint16_t id, const char* body);

  SerialLine& line_;
};

#endif  // KIVO_PROTOCOL_IO_H
