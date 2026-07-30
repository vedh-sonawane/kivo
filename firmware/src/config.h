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

#endif  // KIVO_CONFIG_H
