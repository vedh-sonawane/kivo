#include "serial_line.h"

#include <Arduino.h>

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
