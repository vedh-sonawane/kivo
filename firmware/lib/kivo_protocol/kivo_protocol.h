// Kivo Serial Protocol - device-side framing + integrity.
//
// This module is intentionally free of any Arduino dependency so it compiles
// and is unit-tested on the host (PlatformIO `native` environment) exactly as
// it runs on the Uno. It is the C++ mirror of the backend codec; both obey
// /protocol/README.md. Change one, change the other and the spec together.

#ifndef KIVO_PROTOCOL_H
#define KIVO_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

namespace kivo {

// Max wire-line length (excluding terminator). Matches the backend and the
// SRAM budget in /protocol/README.md §3.
static const size_t KIVO_LINE_MAX = 64;

// CRC-8/SMBUS: poly 0x07, init 0x00, no reflection, no final XOR.
uint8_t crc8(const char* data, size_t len);

enum class FrameType : uint8_t { CMD, RES, EVT };

struct ParsedFrame {
  FrameType type;
  uint16_t id;
  const char* body;  // points into the caller's (mutated) line buffer
};

enum class ParseError : uint8_t { OK, CRC_FAIL, MALFORMED };

// Parse a NUL-terminated line (no trailing newline) in place. On success,
// returns ParseError::OK and fills `out`; the input buffer is modified (NULs
// are written to delimit fields, so `out.body` points inside it).
ParseError parse_frame(char* line, ParsedFrame& out);

// Format "TYPE id body*CRC" into `out`. `body` may be empty. Returns the number
// of characters written (excluding the NUL), or -1 if it would not fit in `cap`.
int format_frame(char* out, size_t cap, const char* type, uint16_t id,
                 const char* body);

}  // namespace kivo

#endif  // KIVO_PROTOCOL_H
