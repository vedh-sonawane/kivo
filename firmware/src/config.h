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

#endif  // KIVO_CONFIG_H
