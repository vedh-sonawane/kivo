// Device-wide configuration constants.
//
// Identity values here are mirrored by the backend's FakeTransport so the
// emulator reports exactly what the real device would.

#ifndef KIVO_CONFIG_H
#define KIVO_CONFIG_H

#define KIVO_BAUD 115200

// Firmware identity, reported via SYS.IDENTIFY and the boot READY event.
#define KIVO_FW_NAME "Kivo"
#define KIVO_FW_VERSION "0.1.0"
#define KIVO_PROTO_VERSION "1"

// -- LCD (HD44780 character display, 4-bit parallel) -------------------------
// The single place the display wiring and geometry are defined. Pins match the
// standard ELEGOO Uno tutorial wiring; change them here only. If the emulator's
// geometry (backend FakeTransport) differs from these, keep the two in step.
#define KIVO_LCD_PIN_RS 12
#define KIVO_LCD_PIN_EN 11
#define KIVO_LCD_PIN_D4 5
#define KIVO_LCD_PIN_D5 4
#define KIVO_LCD_PIN_D6 3
#define KIVO_LCD_PIN_D7 2
#define KIVO_LCD_COLS 16
#define KIVO_LCD_ROWS 2

// -- Sensors -----------------------------------------------------------------
// Photoresistor (light) on an analog pin. Wire it as a divider: LDR from 5V to
// A0, and a ~10k resistor from A0 to GND. Reads 0..1023 (raw ADC). Its change
// threshold sits above the sensor's noise floor so an idle reading stays quiet.
#define KIVO_SENSOR_LIGHT_PIN A0
#define KIVO_SENSOR_LIGHT_CHANGE 8

// PIR motion sensor (presence) on a digital pin. Its OUT pin drives HIGH while a
// warm body is detected, LOW otherwise; VCC->5V, GND->GND. Any free digital pin
// works (avoid the LCD pins 2-5,11,12 and the serial pins 0,1). Reads 0 or 1.
#define KIVO_SENSOR_PRESENCE_PIN 7

// HC-SR04 ultrasonic range finder (distance) — how close the nearest object is,
// in centimetres. TRIG is an output pulse, ECHO an input whose HIGH time encodes
// the distance. Wire VCC->5V, GND->GND, TRIG->pin 9, ECHO->pin 10 (the Uno is
// 5V, so ECHO connects directly — no level divider needed). Its change threshold
// is a few cm so normal jitter doesn't spam the link.
#define KIVO_SENSOR_DISTANCE_TRIG_PIN 9
#define KIVO_SENSOR_DISTANCE_ECHO_PIN 10
#define KIVO_SENSOR_DISTANCE_CHANGE 5

// How often subscribed sensors are sampled before a change is streamed. Tuning
// this trades responsiveness against link chatter; the per-reading "how much
// change is worth reporting" now lives on each Sensor (see kivo.h).
#define KIVO_SENSOR_SAMPLE_MS 200

// -- Expressions -------------------------------------------------------------
// RGB LED for Kivo's mood colour. The Uno's PWM pins are taken (LCD 3/5/11,
// ultrasonic 9/10), so this is digital colour: each channel on/off, giving the
// 7 primaries. Wire each leg through a ~220R resistor; common cathode to GND.
// If your LED is common-anode (common leg to 5V), set KIVO_LED_ACTIVE_LOW 1.
#define KIVO_LED_PIN_R 6
#define KIVO_LED_PIN_G 8
#define KIVO_LED_PIN_B A1
#define KIVO_LED_ACTIVE_LOW 0

// Buzzer for Kivo's chirps. One pin driven with tone() (non-blocking). A passive
// buzzer plays pitches; an active buzzer just clicks/buzzes. Other leg to GND.
#define KIVO_BUZZER_PIN A2

// -- Protocol vocabulary (mirror of the backend's names in kivo/protocol.py) --
// The shared /protocol/README.md spec is the contract that keeps the two in
// step. #defines (not const char*) so unused entries cost no flash. Operation
// *names* live only at their row in the handler registry (kivo.cpp).
#define KIVO_STATUS_OK "OK"
#define KIVO_STATUS_ERR "ERR"
#define KIVO_EVT_READY "READY"
#define KIVO_EVT_ERROR "ERROR"
#define KIVO_EVT_SENSOR "SENSOR"
#define KIVO_PAYLOAD_PONG "PONG"
#define KIVO_ERR_CRC_FAIL 1
#define KIVO_ERR_MALFORMED 2
#define KIVO_ERR_UNKNOWN_OP 3
#define KIVO_ERR_BAD_ARGS 4
// 5 BUSY, 6 INTERNAL are defined by the spec for future use.
#define KIVO_ERRMSG_CRC_FAIL "crc_fail"
#define KIVO_ERRMSG_MALFORMED "malformed"
#define KIVO_ERRMSG_UNKNOWN_OP "unknown_op"
#define KIVO_ERRMSG_BAD_ARGS "bad_args"

#endif  // KIVO_CONFIG_H
