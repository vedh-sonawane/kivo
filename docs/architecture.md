# Kivo - Architecture Overview

Kivo is an AI-capable physical desk companion built around an **ELEGOO Uno R3**
(ATmega328P). This document explains the shape of the system and the reasoning behind
it. Individual decisions with trade-offs are recorded as ADRs in `docs/adr/`.

## Guiding principles

1. **The Uno is the hands; the host is the brain.** The Uno exposes *capabilities*
   (write to the LCD, set an LED, read a sensor). All decision-making - logic,
   scheduling, AI, automation, logging - lives on the host. The Uno stores as little
   state as possible.
2. **The Uno is a hard design constraint, not a stepping stone.** 32 KB flash, 2 KB
   SRAM, one USB-serial UART. We build the best system we can *around* it, and we do not
   architect for hardware we may never own.
3. **Optimise for clarity, maintainability, and learning.** This is a long-lived
   personal project. We avoid both hobby-grade shortcuts and enterprise-grade
   over-engineering. Every abstraction must earn its place *today*.
4. **Vertical slices, not demos.** Each capability is built end to end (host API →
   protocol → firmware → hardware → response) rather than as an isolated sketch.

## System shape

```
                    ┌──────────────────────────────────────────┐
   future:          │  Dashboard (web / desktop)               │
                    └───────────────▲──────────────────────────┘
                                    │ HTTP / WebSocket (future)
   ┌────────────────────────────────┴───────────────────────────┐
   │  BACKEND  (Python, host = your Windows PC)                   │
   │                                                              │
   │   cli / api          entry points (CLI now, FastAPI later)   │
   │   device             capability layer: DeviceClient          │
   │   protocol           codec: frames + CRC-8 (mirrors spec)    │
   │   transport          Transport port + Serial / Fake adapters │
   └────────────────────────────────▲───────────────────────────┘
                                    │  Kivo Serial Protocol (KSP)
                                    │  ASCII lines over USB serial
   ┌────────────────────────────────┴───────────────────────────┐
   │  FIRMWARE  (C++ / PlatformIO, ELEGOO Uno R3)                 │
   │                                                              │
   │   main               cooperative loop, no delay()            │
   │   transport          serial line reader / writer            │
   │   dispatcher         op name → handler routing              │
   │   handlers           PING, SYS.IDENTIFY, (future: DISPLAY…)  │
   │   lib/kivo_protocol  frame parse/format + CRC-8 (portable)   │
   │   drivers (future)   LcdDriver, LedDriver, …                 │
   └──────────────────────────────────────────────────────────────┘
```

The **protocol** (`/protocol/README.md`) is the contract between the two halves. It is
implemented twice - once per language - and both implementations are unit-tested against
the same rules. See ADR-0003.

## Repository layout

```
kivo/
  protocol/     The wire-protocol spec - the source of truth for both sides.
  firmware/     PlatformIO project for the Uno (C++).
  backend/      Python package `kivo` - the host software.
  docs/         Architecture overview + ADRs.
```

Everything is one repository so that a protocol change touches the spec, the firmware,
and the backend in a single atomic commit. See ADR-0001.

## Backend layering (dependency direction points downward)

```
cli / api  →  device  →  protocol  →  transport
```

- **transport** knows only how to move lines of text; it knows nothing about Kivo.
  Two implementations: `SerialTransport` (the real Uno) and `FakeTransport` (an
  in-memory stand-in that behaves like the firmware, so the backend is fully testable
  with no hardware attached).
- **protocol** turns `Frame` objects into wire lines and back, and owns the CRC. It has
  no I/O.
- **device** is the capability API (`DeviceClient.ping()`, `.identify()`, and later
  `.display_write(...)`). It correlates responses to commands and routes events.
- **cli / api** are thin entry points that call the device layer.

This is a light ports-and-adapters arrangement. It is justified purely by *today's*
needs: the `FakeTransport` seam is what makes the backend testable and developable
offline. We did not add layers for speculative future transports.

## Firmware structure

The firmware is a PlatformIO project (ADR-0002), not a single `.ino` sketch. It uses a
**cooperative main loop with no blocking `delay()`**, so that many capabilities can be
serviced responsively at once. Serial reception is buffered line-by-line; a completed
line is parsed, its CRC verified, and dispatched by operation name to a handler. Adding
a capability means adding a driver + a handler and registering it - nothing else changes.

To keep native (host) unit testing possible, the pure protocol logic (framing + CRC)
lives in `firmware/lib/kivo_protocol` with **no Arduino dependencies**, so it compiles
and is tested on the host as well as on the device.

## What we are deliberately *not* building yet

Persistence/event database, HTTP API, automation-rule engine, AI integration, and any
dashboard. Each will arrive as its own vertical slice when there is real behaviour to
justify it. The current foundation is shaped so they can be added without rework, but
none of their machinery exists today.
