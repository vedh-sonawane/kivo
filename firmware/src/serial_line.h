// Non-blocking, line-oriented reader/writer over the Arduino hardware serial.
//
// `poll()` is called every loop iteration; it drains whatever bytes are
// available and returns a completed line (without its terminator) or nullptr.
// It never blocks, so the cooperative main loop stays responsive.

#ifndef KIVO_SERIAL_LINE_H
#define KIVO_SERIAL_LINE_H

#include <stdint.h>

#include "kivo_protocol.h"  // for KIVO_LINE_MAX

class SerialLine {
 public:
  void begin(unsigned long baud);

  // Returns a NUL-terminated completed line, or nullptr if none is ready yet.
  // The returned pointer is valid until the next call to poll().
  char* poll();

  // True once if the most recently completed line overflowed the buffer and
  // was discarded; clears the flag. Lets the caller report a malformed frame.
  bool takeOverflow();

  void sendLine(const char* line);

 private:
  char buffer_[kivo::KIVO_LINE_MAX + 1];
  uint8_t length_ = 0;
  bool overflow_ = false;
  bool overflowLatched_ = false;
};

#endif  // KIVO_SERIAL_LINE_H
