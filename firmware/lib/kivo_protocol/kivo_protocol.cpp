#include "kivo_protocol.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

namespace kivo {

uint8_t crc8(const char* data, size_t len) {
  uint8_t crc = 0x00;
  for (size_t i = 0; i < len; ++i) {
    crc ^= static_cast<uint8_t>(data[i]);
    for (uint8_t bit = 0; bit < 8; ++bit) {
      if (crc & 0x80) {
        crc = static_cast<uint8_t>((crc << 1) ^ 0x07);
      } else {
        crc = static_cast<uint8_t>(crc << 1);
      }
    }
  }
  return crc;
}

// Return 0..15 for a hex digit, or -1 if `c` is not one.
static int hex_value(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  return -1;
}

ParseError parse_frame(char* line, ParsedFrame& out) {
  size_t len = strlen(line);
  if (len > KIVO_LINE_MAX) return ParseError::MALFORMED;

  // The checksum is the final "*XX". '*' is reserved, so there is exactly one.
  char* star = strchr(line, '*');
  if (star == nullptr) return ParseError::MALFORMED;
  if (star[1] == '\0' || star[2] == '\0' || star[3] != '\0') {
    return ParseError::MALFORMED;  // must be exactly two chars after '*'
  }
  int hi = hex_value(star[1]);
  int lo = hex_value(star[2]);
  if (hi < 0 || lo < 0) return ParseError::MALFORMED;
  uint8_t given = static_cast<uint8_t>((hi << 4) | lo);

  *star = '\0';  // terminate the payload for the CRC check and field parsing
  uint8_t computed = crc8(line, static_cast<size_t>(star - line));
  if (computed != given) return ParseError::CRC_FAIL;

  // payload = "TYPE id body"; split off TYPE and id, keep body intact.
  char* sp1 = strchr(line, ' ');
  if (sp1 == nullptr) return ParseError::MALFORMED;
  *sp1 = '\0';
  char* rest = sp1 + 1;

  char* body = const_cast<char*>("");
  char* sp2 = strchr(rest, ' ');
  if (sp2 != nullptr) {
    *sp2 = '\0';
    body = sp2 + 1;
  }
  char* id_str = rest;

  FrameType type;
  if (strcmp(line, "CMD") == 0) {
    type = FrameType::CMD;
  } else if (strcmp(line, "RES") == 0) {
    type = FrameType::RES;
  } else if (strcmp(line, "EVT") == 0) {
    type = FrameType::EVT;
  } else {
    return ParseError::MALFORMED;
  }

  char* end = nullptr;
  unsigned long id = strtoul(id_str, &end, 10);
  if (id_str[0] == '\0' || *end != '\0' || id > 0xFFFF) {
    return ParseError::MALFORMED;
  }

  out.type = type;
  out.id = static_cast<uint16_t>(id);
  out.body = body;
  return ParseError::OK;
}

int format_frame(char* out, size_t cap, const char* type, uint16_t id,
                 const char* body) {
  int n;
  if (body != nullptr && body[0] != '\0') {
    n = snprintf(out, cap, "%s %u %s", type, static_cast<unsigned>(id), body);
  } else {
    n = snprintf(out, cap, "%s %u", type, static_cast<unsigned>(id));
  }
  if (n < 0 || static_cast<size_t>(n) >= cap) return -1;

  uint8_t crc = crc8(out, static_cast<size_t>(n));
  int m = snprintf(out + n, cap - static_cast<size_t>(n), "*%02X", crc);
  if (m < 0 || static_cast<size_t>(n + m) >= cap) return -1;
  return n + m;
}

}  // namespace kivo
