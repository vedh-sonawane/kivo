# Kivo — Project Progress Brief (for ChatGPT context)

## What Kivo is
An AI-capable physical **desk companion** built around a single **ELEGOO Uno R3**
(ATmega328P: 32 KB flash, 2 KB SRAM, one USB-serial UART). Philosophy: the Uno is the
"hands" (exposes hardware capabilities); a Python backend on a Windows PC is the "brain"
(all logic). They talk over a small, robust, checksummed serial protocol.

## Hard constraints / working principles
- **Uno R3 is a fixed design constraint** — do NOT architect for other/future boards.
- Optimize for **clarity, maintainability, and learning**; avoid both hobby shortcuts and
  enterprise over-engineering. Every abstraction must earn its place today.
- **No hardcoding**: pins, ports, protocol tokens, timings, geometry all centralized.
- **No git/GitHub operations** are performed by the assistant (user controls version history).
- Build **complete vertical slices** (host API → protocol → firmware → hardware → response),
  not isolated demos.

## Tech stack
- **Firmware:** C++ via **PlatformIO** (not Arduino IDE). Board env `uno`; host-test env
  `native` (Unity). Cooperative main loop, no blocking `delay()`, no `String` (fixed char
  buffers). Vendor libs isolated behind own classes.
- **Backend:** Python 3.14, package `kivo`, installed editable with pyserial. Synchronous
  core (async deferred until an API layer needs it). Tests via pytest.
- **Host:** Windows 11, device on **COM3** (genuine Arduino Uno, VID:PID 2341:0043).
  PlatformIO 6.1.19 on PATH. MSYS2 mingw64 gcc at C:\msys64 (needed for `native` tests,
  which must be run from a Git Bash / MSYS2 shell, NOT PowerShell).

## Architecture
Backend layering (deps point downward): `cli → device → protocol → transport`.
- `transport/`: `Transport` port; `SerialTransport` (real Uno) and `FakeTransport`
  (in-memory firmware emulator used for offline dev + tests). `resets_on_connect` flag
  drives the boot handshake.
- `protocol/`: `codec` (framing + CRC-8), `messages`, `names` (centralized vocabulary),
  `errors`.
- `device/`: `DeviceClient` (capability API + response correlation + event handling),
  `Identity`, `SensorReading`.
- `cli.py`: subcommands `ping`, `identify`, `display`, `clear`, `read`, `watch`.

Firmware structure: `main.cpp` (cooperative loop) → `SerialLine` (non-blocking line I/O) →
`Dispatcher` (op → handler) → handlers, replying via `ProtocolIO`. Handlers receive a
`DeviceContext{ io, display, sensors }` (no globals). `lib/kivo_protocol/` holds the
Arduino-independent framing+CRC (host-unit-testable, mirrors the backend codec).
Peripherals: `LcdDisplay` (wraps Arduino `LiquidCrystal`), `SensorManager` + `Sensor`/
`AnalogSensor`.

## Wire protocol — Kivo Serial Protocol (KSP) v1
- One ASCII line per message, `\n`-terminated, ≤ 64 bytes.
- Frame: `TYPE id body*CRC8`  (CRC-8/SMBUS, poly 0x07; `*` reserved as checksum separator).
- Types: `CMD` (host→device), `RES` (reply, correlated by id), `EVT` (unsolicited, id 0).
- Operations: `PING`→`OK PONG`; `SYS.IDENTIFY`→`OK <name> <ver> <proto>`;
  `DISPLAY.WRITE <row> <col> <text>`→`OK`; `DISPLAY.CLEAR`→`OK`;
  `SENSOR.READ <name>`→`OK <value>`; `SENSOR.SUBSCRIBE <name>`/`SENSOR.UNSUBSCRIBE <name>`→`OK`.
- Events: `READY <name> <ver> <proto>` (boot); `ERROR <code> <msg>` (frame-level);
  `SENSOR <name> <value>` (streamed when subscribed).
- Error codes: 1 CRC_FAIL, 2 MALFORMED (both reported as ERROR events), 3 UNKNOWN_OP,
  4 BAD_ARGS (reported as correlated RES ERR).

## Hardware wiring (in firmware/src/config.h — single source)
- LCD (16×2, HD44780, 4-bit parallel): RS=12, E=11, D4=5, D5=4, D6=3, D7=2.
- Light sensor (photoresistor): analog pin **A0**, sample every 200 ms,
  change-threshold 8 (on the 0–1023 analog scale; only emits an event when the reading
  moves by ≥ 8, so an idle sensor stays quiet). Non-blocking emission with backpressure.

## What is BUILT and VERIFIED
1. **Foundation** — monorepo (`protocol/`, `firmware/`, `backend/`, `docs/` with ADRs
   0001–0004), the protocol + both codecs, handshake. ✅
2. **LCD output slice** — `DISPLAY.WRITE`/`DISPLAY.CLEAR`, host defaults row/col to 0,
   device validates geometry (BAD_ARGS) and truncates at row edge. **Confirmed on real
   hardware** (text shows on the LCD).
3. **Sensor input slice** — device→host event streaming. `SensorManager` samples
   subscribed sensors on one cadence and emits `SENSOR` events on change; `SENSOR.READ`
   for one-shot; CLI `read` (one-shot) and `watch` (live stream). This completes the
   device→host direction of the architecture.
   **VERIFIED ON REAL HARDWARE (2026-07-30):** a photoresistor voltage divider on pin A0
   (5V → LDR → A0 tap → 10 kΩ → GND) is flashed and confirmed live — `kivo read light`
   returns steady high values in light and low values when covered; `kivo watch light`
   streams changes. Debugging note: a railed 1022 = missing/loose GND leg; jittery
   mid-scale ~500 = a loose/floating connection (reseat the thin LDR/resistor legs).

4. **The Brain (autonomous host loop)** — `backend/src/kivo/brain/`. A persistent
   host-side mind that owns one long-lived connection, keeps a `WorldState`, and runs
   pure `Behavior`s that return `Action`s (`ShowText`/`ClearScreen`) which the `Brain`
   applies to the device. First behaviours: `Greeter` (greets on wake) and `LightMood`
   (turns raw light readings into "dark/dim/bright" and narrates the room on the LCD,
   updating only when the level changes; thresholds configurable). New CLI command
   `kivo run` = live companion mode. Single-threaded (ADR-0004); events queued and
   processed on the loop (no re-entrancy). This is the seam future automation rules and
   local-AI reasoning plug into as more behaviours.
   **Status: built + verified against the emulator (41 backend tests, incl. an
   end-to-end Brain run). On-hardware `kivo run` demo still pending** (board was
   unplugged at build time). No firmware change was needed — the Brain is host-only.

5. **Local AI voice** — `backend/src/kivo/ai/`. A free, offline AI speaks as Kivo via a
   local **Ollama** server (no paid API). `AiClient` port + `OllamaClient` (stdlib
   `urllib`, no new dependency) + `FakeAiClient` for tests. `AiNarrator` is a `Behavior`
   that, on wake and on light-mood changes, asks the model for a short in-character line
   and shows it (trimmed to the 16-char LCD); it **degrades gracefully** (stays quiet) if
   Ollama is unreachable. New: `kivo run --ai [--model NAME]`. Config: `KIVO_OLLAMA_URL`,
   `KIVO_OLLAMA_MODEL` (default `llama3`), `KIVO_AI_TIMEOUT`; requests set `keep_alive` so
   the model stays resident.
   **Verified LIVE against real Ollama** (no board needed): produced e.g. "Hello Beautiful
   Day" / "Lights!". **Perf finding on this PC:** `llama3` (8B) is ~16 s warm, ~105 s cold
   — too slow to feel snappy. Design decision: kept the narrator **synchronous** (simple)
   and instead recommend pulling a **small model** (e.g. `llama3.2:3b`, `qwen2.5:1.5b`) for
   ~1-2 s reactions; only add background-threading later if a small model still feels janky
   (avoid premature complexity). AI call currently blocks the single-threaded Brain loop —
   fine for infrequent reactions with a small model; documented as the future async seam.

6. **Refinements (2026-07-30)** — from live use:
   - **Hysteresis** in light classification (`LightClassifier`, shared by `LightMood` and
     `AiNarrator`): a value near a threshold no longer flaps dark<->dim on sensor noise;
     leaving a band requires crossing by a `margin` (default 40), while large jumps still
     land on the right band. Fixes "it kept changing dark/dim on its own".
   - **Word-boundary trimming** of AI lines to the 16-char LCD (no more half-word cut off
     at the right edge).
   - **Time-of-day awareness** (`part_of_day`, `TimeGreeter`): default greeting is now
     "Good morning/afternoon/evening" / "Hi, night owl"; the AI narrator also gets the
     time-of-day in its prompt so its lines are time-appropriate.
   - Clearer Ollama errors (a 404 now says "is it pulled? try: ollama pull <model>").

7. **Calibration + AI greeting + robustness (2026-07-30, from live use)** —
   - **Light was mislabeled** (bright room read "dim") because thresholds were hardcoded
     guesses that didn't match the user's sensor. Fixed properly with **per-sensor
     calibration**: `kivo calibrate light` measures the real bright & dark readings and
     saves derived thresholds (`backend/src/kivo/calibration.py`; JSON at
     `~/.kivo/calibration.json` or `$KIVO_CALIBRATION_PATH`). `kivo run` loads them; no
     more magic numbers. `compute_thresholds` puts band edges at 33%/66% of the measured
     span.
   - **AI voice** (`AiNarrator`, used by `run --ai` as `[AiNarrator(row0), LightMood(row1)]`):
     a **unique, time-aware greeting** on wake (prompt includes the real clock time +
     part of day, e.g. "9:30 PM, evening"), then a **fresh short AI line each time the
     light level actually changes** (bright/dim/dark). The first reading is recorded
     silently so the greeting isn't clobbered; uses the calibrated thresholds. Verified
     live on llama3: greeting "Moonlit moment", room-dark reaction "Darkness falls".
     (Removed the interim `AiGreeter`; `AiNarrator` covers greeting + reactions. Non-AI
     `run` still uses fixed `TimeGreeter`.)
   - **Clean errors**: a busy/missing serial port now prints a friendly message (new
     `TransportError`) instead of a raw traceback.

8. **Two live-use fixes + presence sensing (2026-07-31)** —
   - **LCD "random words" fixed**: garbled lines like "Morningt isllsd" were *stale
     characters*, not the model — the LCD writes text in place and never blanks the
     rest of a row, so a short new line left the tail of a longer old one behind.
     Fixed once for all behaviours in `Brain._execute`: every line is right-padded
     to the full 16 columns (`_LCD_COLS`, mirroring firmware) so it wipes the row.
   - **AI lag fixed**: the model call was blocking Kivo's single loop, so even the
     factual light row waited seconds. `AiNarrator` now generates on a **background
     daemon thread**; a trigger (wake, light change, arrival) just queues a prompt
     and returns instantly, so the factual row reacts immediately and the AI line
     appears the moment it's ready — delivered on the Brain's own loop via a new
     `Behavior.on_tick()` hook (polled each `step()`), so action application stays
     single-threaded (ADR-0004). Rapid triggers coalesce to the latest line.
   - **Presence (PIR) — Slice 1 of two**: Kivo now senses when a person arrives or
     leaves. Firmware gained a digital-sensor path: `Sensor` carries its own
     `changeThreshold()` (analog light stays 8 to beat noise; a digital sensor uses
     1 — any 0<->1 flip matters) and a `begin()` for pin setup; new `DigitalSensor`
     (`digitalRead`). `SensorManager` dropped its single global threshold (now
     per-sensor) and gained `begin()`. New sensor **`presence`** = `DigitalSensor`
     on **digital pin 7**, streaming 0/1. Backend: `PresenceGreeter` (deterministic
     "Welcome back!" / "See you soon", primes silently); `AiNarrator` also watches
     `presence` and speaks an AI welcome on arrival / goodbye on leaving, reusing
     its one worker thread. `kivo run` now subscribes light + presence.
     **Status: built; firmware compiles (RAM ~32%, Flash ~31%); NOT yet flashed /
     tested on hardware.** Slice 2 (next) = ultrasonic HC-SR04 *proximity*, which
     needs a non-blocking echo read (pulseIn blocks the cooperative loop).

9. **Scrolling LCD — no more cut-off words (2026-07-31)** — the long-standing
   "half phrases / unfinished sentences" problem is fixed by *not truncating*.
   New `RowScroller` (`brain/scroller.py`) is a per-row marquee: the whole line
   is kept on the host and only the current 16-char window is sent to the device;
   a line longer than the screen slides left one character per shift (loops with
   a small gap, brief hold on the opening words) so every word is revealed. The
   Brain owns one scroller per row, loads it in `_execute`, and advances it in a
   new `_animate()` each `step()` — smooth precisely because the AI generation is
   off-loop now. Lines that fit are shown static (padded). `AiNarrator` stopped
   trimming to 16 chars (`fit_line` -> `one_line`: just flatten whitespace + an
   80-char word-boundary safety cap for pathological output) and its persona
   prompt now asks for a short **complete** line. Entirely host-side — **no
   firmware reflash needed.**

10. **Proximity (ultrasonic HC-SR04) — Slice 2 (2026-07-31)** — Kivo now senses
    *how close* you are and perks up when you lean in. New sensor **`distance`**
    (cm to the nearest object). The echo pulse can take ~25 ms, so rather than
    block (`pulseIn`) it's a **non-blocking state machine** (IDLE -> WAIT_RISING
    -> WAIT_FALLING) advanced by a new `Sensor::update()`, which `SensorManager`
    now calls for every sensor on every loop (separate from the 200 ms emission
    cadence); `read()` returns the last completed measurement. The 10 µs trigger
    is a tolerated micro-delay. Pins **TRIG=9, ECHO=10** (Uno is 5 V, ECHO wired
    direct). Backend: `ProximityGate` (binary "leaning in?" with hysteresis,
    close < 20 cm), `ProximityGreeter` (deterministic lean-in line), and
    `AiNarrator` also reacts to a lean-in via the distance sensor. `kivo run`
    subscribes light + presence + distance. **Status: built; firmware compiles
    (RAM ~35%, Flash ~33%); needs a reflash; not yet hardware-tested.** This
    completes both companion senses (PIR presence + ultrasonic proximity).

11. **Presence fusion + codebase consolidation (2026-07-31)** —
    - **Presence fusion**: PIR motion-only presence was wrong (said "bye" when a
      user sat still, "welcome" when they moved). Now presence is **distance-
      driven** via `PresenceEstimator`: present while within ~120 cm (hysteresis),
      PIR motion only *adds* presence (never marks you gone), and "gone" needs far
      AND no motion for a few seconds — re-checked every tick so it fires in a
      still room. Sitting still up close never triggers a goodbye. Host-side only.
    - **Consolidation**: the file sprawl was collapsed on request. **Backend: 25
      → 8 files** (`__init__`, `protocol`, `transport`, `device`, `brain`, `ai`,
      `calibration`, `cli` — cli now holds Settings). Package import paths are
      unchanged; only submodule paths went away. **Firmware: 21 → 6 files**
      (`config.h`, `kivo.h`, `kivo.cpp`, `main.cpp`, plus the host-tested
      `lib/kivo_protocol/{h,cpp}`). No behaviour changed.

Test status: **79 backend pytest pass; 6 firmware native Unity tests pass.**
Firmware footprint: **RAM ~35%, Flash ~33%.**

## Correct setup order for the user
1. Stop any running `kivo run` (Ctrl+C) to free the port.
2. `kivo --port COM3 calibrate light`  (follow prompts: make bright, then cover it).
3. `kivo --port COM3 run --ai --model llama3.2:3b`  (small model = fast; `-v` to watch).

## Constraints reminder
- **No paid services / no paid APIs, ever.** AI is a **local Ollama model** (free, offline).
- **No git operations** performed by the assistant.

## Current state
Kivo has a **Brain** and now a **local-AI voice**. `kivo run` = deterministic companion
(greets, narrates room light); `kivo run --ai` = a local LLM speaks as Kivo. Brain +
deterministic behaviours verified end-to-end on the emulator; the AI path verified live
against real Ollama. Remaining live confirmation: the on-hardware `kivo run` / `run --ai`
demo (needs the Uno reconnected on COM3) and a small fast model pulled for snappiness.

## Immediate next steps
1. Reconnect the Uno; `kivo --port COM3 run` (watch LCD greet + track light; `-v` shows
   decisions). Then `kivo --port COM3 run --ai --model llama3.2:3b` once a small model is
   pulled (`ollama pull llama3.2:3b`).
2. Grow the companion: presence sensing (PIR/ultrasonic) so it knows you're there;
   expressions (LED/buzzer/servo); richer AI behaviours; automation rules; event logging.
