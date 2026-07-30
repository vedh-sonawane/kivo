// Host-side unit tests for the portable Kivo protocol library.
// Run with: pio test -e native

#include <string.h>
#include <unity.h>

#include "kivo_protocol.h"

void setUp() {}
void tearDown() {}

// CRC-8/SMBUS check value: the standard test vector "123456789" -> 0xF4.
// This is the exact contract the backend's crc8 also asserts.
void test_crc8_standard_check_value() {
  TEST_ASSERT_EQUAL_UINT8(0xF4, kivo::crc8("123456789", 9));
}

void test_crc8_empty_is_zero() {
  TEST_ASSERT_EQUAL_UINT8(0x00, kivo::crc8("", 0));
}

void test_format_then_parse_round_trips() {
  char line[kivo::KIVO_LINE_MAX + 1];
  int n = kivo::format_frame(line, sizeof(line), "CMD", 7, "DISPLAY.WRITE Hi there");
  TEST_ASSERT_GREATER_THAN(0, n);

  kivo::ParsedFrame frame;
  kivo::ParseError err = kivo::parse_frame(line, frame);
  TEST_ASSERT_EQUAL(kivo::ParseError::OK, err);
  TEST_ASSERT_EQUAL(kivo::FrameType::CMD, frame.type);
  TEST_ASSERT_EQUAL_UINT16(7, frame.id);
  TEST_ASSERT_EQUAL_STRING("DISPLAY.WRITE Hi there", frame.body);
}

void test_parse_detects_bad_crc() {
  // A valid frame with its checksum clobbered.
  char line[] = "CMD 1 PING*00";
  kivo::ParsedFrame frame;
  TEST_ASSERT_EQUAL(kivo::ParseError::CRC_FAIL, kivo::parse_frame(line, frame));
}

void test_parse_detects_missing_checksum() {
  char line[] = "CMD 1 PING";
  kivo::ParsedFrame frame;
  TEST_ASSERT_EQUAL(kivo::ParseError::MALFORMED, kivo::parse_frame(line, frame));
}

void test_parse_body_less_frame() {
  // "RES 1 OK" style still parses; here a command with only an op.
  char line[kivo::KIVO_LINE_MAX + 1];
  kivo::format_frame(line, sizeof(line), "CMD", 2, "PING");
  kivo::ParsedFrame frame;
  TEST_ASSERT_EQUAL(kivo::ParseError::OK, kivo::parse_frame(line, frame));
  TEST_ASSERT_EQUAL_STRING("PING", frame.body);
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_crc8_standard_check_value);
  RUN_TEST(test_crc8_empty_is_zero);
  RUN_TEST(test_format_then_parse_round_trips);
  RUN_TEST(test_parse_detects_bad_crc);
  RUN_TEST(test_parse_detects_missing_checksum);
  RUN_TEST(test_parse_body_less_frame);
  return UNITY_END();
}
