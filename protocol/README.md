# Kivo Serial Protocol (KSP) - v1

This document is the **single source of truth** for how the backend (host) and the
firmware (Arduino Uno) talk to each other. Both sides implement this spec:

- Backend codec: `backend/src/kivo/protocol/`
- Firmware codec: `firmware/lib/kivo_protocol/`

If you change anything here, you change both implementations in the same commit.
That is the whole reason firmware and backend live in one repository.

---

## 1. Design goals

1. **Robust, not ad hoc.** Every message is framed and integrity-checked. A corrupted
   byte on the wire is detected and rejected, never silently misinterpreted.
2. **Human-readable.** You can watch the traffic in a serial monitor and understand it.
   This matters far more for a project you learn from than raw byte efficiency.
3. **Cheap on the device.** The Uno has 2 KB of SRAM. Messages are short ASCII lines
   parsed in fixed-size buffers with no dynamic allocation.
4. **Capability-oriented, not pin-oriented.** The host says `DISPLAY.WRITE Hello`, never
   "set pin 7 high". Wiring lives in firmware; the host only knows capabilities.
5. **Extensible.** New capabilities are new *operations*. Adding one never changes the
   framing, the codec, or any existing operation.

## 2. Physical layer

| Parameter | Value                          |
|-----------|--------------------------------|
| Transport | USB serial (CDC)               |
| Baud rate | 115200                         |
| Framing   | 8 data bits, no parity, 1 stop |

## 3. Message = one line

A message is a single line of ASCII text terminated by `\n` (LF, 0x0A).
A `\r` (CR) immediately before the LF is tolerated and ignored, so both `\n` and
`\r\n` line endings work.

**Maximum line length is 64 bytes** (excluding the terminator). This is a deliberate
SRAM budget, not an arbitrary limit. A line longer than this is rejected (see §8).

## 4. Frame grammar

```
line    = type SP id SP body "*" crc
type    = "CMD" | "RES" | "EVT"
id      = 1*5DIGIT            ; decimal, 0..65535
body    = op-and-args         ; operation-specific, MAY contain spaces
crc     = 2HEXDIG             ; uppercase CRC-8 of everything before "*"
```

- `SP` is a single ASCII space (0x20).
- `*` (0x2A) is **reserved** as the checksum separator and MUST NOT appear anywhere
  else in a line. (v1 payloads are plain text where this is a non-issue; a future
  binary payload would define an escaping rule here.)
- The checksum is computed over the raw bytes **before** the `*`, i.e. over
  `type SP id SP body`.

### CRC-8

Polynomial `0x07`, initial value `0x00`, no input/output reflection, no final XOR.
(Commonly called CRC-8/SMBUS.) Reference implementations are identical on both sides:
`backend/src/kivo/protocol/crc8.py` and `firmware/lib/kivo_protocol/kivo_protocol.cpp`.

## 5. Message types

### 5.1 `CMD` - command (host → device)

The host asks the device to do something.

```
CMD <id> <op> [args]*<crc>
```

- `<id>` is a monotonically increasing correlation id chosen by the host (1..65535,
  wrapping back to 1). The device echoes it in the matching `RES`.
- `<op>` is an uppercase, dot-namespaced operation name, e.g. `PING`, `SYS.IDENTIFY`,
  `DISPLAY.WRITE`. No spaces.
- `[args]` is everything after the op; each operation defines its own argument format.

### 5.2 `RES` - response (device → host)

Exactly one `RES` is returned for each `CMD` the device successfully parses, carrying
the same `<id>`.

```
RES <id> OK  [data]*<crc>       ; success, optional operation-defined data
RES <id> ERR <code> <message>*<crc>   ; failure
```

Error codes:

| Code | Name          | Meaning                                             |
|------|---------------|-----------------------------------------------------|
| 3    | UNKNOWN_OP    | The operation name is not recognized.               |
| 4    | BAD_ARGS      | The operation exists but the arguments are invalid. |
| 5    | BUSY          | The device cannot service the request right now.    |
| 6    | INTERNAL      | An internal firmware error occurred.                |

(Codes 1 and 2 are reserved for frame-level failures, which cannot be correlated to an
id and are reported as events - see §8.)

### 5.3 `EVT` - event (device → host, unsolicited)

The device reports something that was not requested. Events always use `id = 0`.

```
EVT 0 <name> [data]*<crc>
```

Defined events:

| Name    | Data                                | When                                   |
|---------|-------------------------------------|----------------------------------------|
| `READY` | `<fw-name> <fw-version> <proto>`    | Emitted once at boot / after reset.    |
| `ERROR` | `<code> <message>`                  | A frame-level failure (see §8).        |

Future capabilities (e.g. sensor readings, button presses) will add new event names.

## 6. Handshake & core operations (v1)

### 6.1 Core / handshake

These operations have no hardware dependency and exist from day one so the link itself
can be validated end-to-end.

| Op             | Args | Success response          | Purpose                          |
|----------------|------|---------------------------|----------------------------------|
| `PING`         | -    | `OK PONG`                 | Liveness / round-trip check.     |
| `SYS.IDENTIFY` | -    | `OK <name> <ver> <proto>` | Who am I, what version, what KSP. |

On boot the device emits `EVT 0 READY <name> <ver> <proto>` so the host can detect a
connection or an unexpected reset without polling.

### 6.2 Display capability

Controls a character LCD. The op is capability-oriented: the host says *what* to show,
never *how* the screen is wired.

| Op              | Args                | Success response | Purpose                       |
|-----------------|---------------------|------------------|-------------------------------|
| `DISPLAY.WRITE` | `<row> <col> <text>`| `OK`             | Write text at a cell.         |
| `DISPLAY.CLEAR` | -                   | `OK`             | Clear the whole screen.       |

- `<row>` and `<col>` are zero-based decimal integers. `<text>` is the rest of the line
  and may contain spaces (but not the reserved `*`).
- The device knows its own geometry (a 16×2 LCD here). Out-of-range `<row>`/`<col>`, or a
  missing/non-numeric coordinate, yields `RES <id> ERR 4 bad_args`. Text longer than the
  space remaining on the row is truncated by the device - screen dimensions are a device
  property the host does not hardcode.
- The host convenience API defaults `<row>` and `<col>` to `0` so callers can write
  `display_write("Hello")` without positioning.

### 6.3 Sensor capability

Reads sensors and, on request, streams their values as events. The device names its
sensors; the host addresses them by name and never needs to know a pin or wiring.

| Op                    | Args     | Success response | Purpose                          |
|-----------------------|----------|------------------|----------------------------------|
| `SENSOR.READ`         | `<name>` | `OK <value>`     | One-shot read of a sensor.       |
| `SENSOR.SUBSCRIBE`    | `<name>` | `OK`             | Begin streaming that sensor.     |
| `SENSOR.UNSUBSCRIBE`  | `<name>` | `OK`             | Stop streaming that sensor.      |

- `<name>` is a device-defined sensor id (e.g. `light`). An unknown name yields
  `RES <id> ERR 4 bad_args`.
- `<value>` is a raw integer in device units (e.g. a 0–1023 ADC reading). The *meaning*
  (brightness, temperature…) is the host's to interpret - the device only reports numbers.

**Streaming.** While subscribed, the device samples the sensor on its own timer and emits

```
EVT 0 SENSOR <name> <value>
```

only when the value changes by at least a device-defined threshold (so an idle sensor is
quiet). Sampling interval and threshold are device configuration, not part of the wire
protocol. Emission is best-effort: if the host is not draining the link, the device drops
samples rather than blocking. Subscriptions are per-connection and reset when the device
reboots (which happens on every host reconnect), so streams never outlive their listener.

## 7. Example exchange

(Checksums shown as `XX` are illustrative; the authoritative values are asserted by the
codec unit tests on both sides.)

```
device →  EVT 0 READY Kivo 0.1.0 1*XX      ; device booted
host   →  CMD 1 SYS.IDENTIFY*XX
device →  RES 1 OK Kivo 0.1.0 1*XX
host   →  CMD 2 PING*XX
device →  RES 2 OK PONG*XX
host   →  CMD 3 DISPLAY.WRITE 0 0 Hello*XX  ; write "Hello" at row 0, col 0
device →  RES 3 OK*XX
host   →  CMD 4 DISPLAY.CLEAR*XX
device →  RES 4 OK*XX
host   →  CMD 5 BOGUS*XX
device →  RES 5 ERR 3 unknown_op*XX
```

## 8. Error handling on the wire

- **CRC mismatch** → the frame is untrusted; its id cannot be believed. The device
  discards it and emits `EVT 0 ERROR 1 crc_fail`. (Code 1 = CRC_FAIL.)
- **Malformed frame** (missing fields, bad type, oversized line) → discarded; the device
  emits `EVT 0 ERROR 2 malformed`. (Code 2 = MALFORMED.)
- **Parsed but unknown/invalid op** → a normal correlated `RES <id> ERR ...` (§5.2),
  because the id *is* trustworthy in this case.

The host applies a timeout while waiting for a `RES`. A missing response is a transport
failure, surfaced to the caller - the protocol never blocks forever.

## 9. Versioning

The single integer `<proto>` in `READY` / `SYS.IDENTIFY` is the protocol version (`1`).
It is bumped only on a breaking change to framing or core semantics. Additive changes
(new operations, new events) do **not** bump it, because they cannot break an existing
peer. The host may warn if the device reports a protocol version it does not support.
