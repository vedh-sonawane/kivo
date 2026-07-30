// Protocol vocabulary — the event names, status tokens, payloads, and error
// codes/messages defined by /protocol/README.md.
//
// This is the firmware mirror of the backend's `protocol/names.py`. The shared
// spec is the contract that keeps the two in step. Operation *names* are not
// listed here on purpose: each is defined exactly once, at its row in the
// handler registry (handlers.cpp), so a second definition would only invite
// drift.
//
// These are #defines rather than `const char*` so unused entries cost no flash
// and each use is inlined by the compiler.

#ifndef KIVO_PROTOCOL_VOCAB_H
#define KIVO_PROTOCOL_VOCAB_H

// RES status tokens (first word of a response body).
#define KIVO_STATUS_OK "OK"
#define KIVO_STATUS_ERR "ERR"

// Event names (device -> host).
#define KIVO_EVT_READY "READY"
#define KIVO_EVT_ERROR "ERROR"

// Fixed response payloads.
#define KIVO_PAYLOAD_PONG "PONG"

// Error codes (see /protocol/README.md §5.2 and §8).
#define KIVO_ERR_CRC_FAIL 1
#define KIVO_ERR_MALFORMED 2
#define KIVO_ERR_UNKNOWN_OP 3
// 4 BAD_ARGS, 5 BUSY, 6 INTERNAL are defined by the spec for future use.

// Human-readable error messages paired with the codes above.
#define KIVO_ERRMSG_CRC_FAIL "crc_fail"
#define KIVO_ERRMSG_MALFORMED "malformed"
#define KIVO_ERRMSG_UNKNOWN_OP "unknown_op"

#endif  // KIVO_PROTOCOL_VOCAB_H
