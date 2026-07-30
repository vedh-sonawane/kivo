# ADR-0002: PlatformIO (not the Arduino IDE) for firmware

- **Status:** Accepted
- **Date:** 2026-07-29

## Context

Arduino firmware is commonly written as a single `.ino` sketch in the Arduino IDE. Kivo
explicitly wants modular, maintainable firmware rather than one large sketch, and wants
tests where they make sense.

## Decision

Build the firmware as a **PlatformIO** project using the Arduino framework for the Uno.

## Rationale

- **Real project structure.** `src/`, `lib/`, `include/`, and `test/` with normal C++
  files instead of one `.ino`. This directly serves the "no giant sketch" requirement.
- **Library & dependency management.** Versions are pinned in `platformio.ini`, so builds
  are reproducible.
- **Native unit testing.** PlatformIO can run tests on the host with the Unity framework.
  We keep the protocol logic Arduino-independent (`lib/kivo_protocol`) so CRC and frame
  parsing are tested on the PC — fast, and no board required.
- **CLI / CI friendly.** `pio run` / `pio test` work headless; the Arduino IDE does not.

## Alternatives considered

- **Arduino IDE + `.ino`:** rejected — the single-sketch model is the exact thing we are
  avoiding, and it has no test story.
- **Bare avr-gcc + Makefile:** maximum control, but we would reimplement what PlatformIO
  already does well, at a cost in clarity that this project does not want to pay.

## Consequences

- Contributors need PlatformIO (CLI or the VS Code extension). Documented in
  `firmware/README.md`.
