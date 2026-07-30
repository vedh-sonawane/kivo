# ADR-0003: A framed, checksummed, text-based serial protocol

- **Status:** Accepted
- **Date:** 2026-07-29

## Context

Firmware and backend communicate over USB serial. We need a message format. The options
range from "print human strings and parse them ad hoc" to a full binary protocol.

## Decision

Define the **Kivo Serial Protocol (KSP)** — a versioned, line-based, checksummed,
capability-oriented text protocol. It is specified once in `/protocol/README.md` and
implemented on both sides. See that document for the grammar.

Key properties: one ASCII line per message; a `type id body*crc8` frame; CRC-8 integrity
check; request/response correlation by id; unsolicited events; capability-named
operations (`DISPLAY.WRITE`, never pin numbers).

## Rationale

- **Ad hoc strings** were explicitly rejected by the project: they have no framing, no
  integrity check, and rot into an unspecified mess.
- **Firmata** is pin-level. It would push wiring knowledge into the host and break the
  "hardware exposes capabilities" principle. Rejected.
- **A binary protocol** (e.g. CBOR, custom TLV) is more compact but far harder to read,
  debug, and learn from. Byte efficiency is not a constraint at 115200 baud with short
  messages. Rejected for v1 — the framing layer is isolated so it could be swapped later
  if a real need ever appears.
- **Text with framing + CRC** hits the sweet spot: you can read it in a serial monitor,
  it is cheap to parse in fixed buffers on 2 KB of SRAM, and corruption is detected.

## Consequences

- The `*` byte is reserved as the checksum separator and cannot appear in payloads. v1
  text payloads never need it; a future binary payload would define escaping.
- Both codecs must stay in lockstep with the spec. They are unit-tested against the same
  rules to enforce this.
- Maximum line length is fixed at 64 bytes to bound SRAM usage.
