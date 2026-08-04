# Kivo firmware

C++ firmware for the ELEGOO Uno R3, built with [PlatformIO](https://platformio.org/)
(see `docs/adr/0002-platformio-firmware.md` for why).

## Layout

```
firmware/
  platformio.ini          build environments (uno, native)
  lib/kivo_protocol/      portable framing + CRC (no Arduino deps, host-testable)
  src/
    config.h              baud, identity, protocol version
    serial_line.*         non-blocking line reader/writer
    protocol_io.*         builds & sends RES / EVT frames
    dispatcher.*          routes a command to its handler
    handlers.*            PING, SYS.IDENTIFY + the handler registry
    main.cpp              cooperative loop wiring it all together
  test/test_protocol/     host-side unit tests (Unity)
```

## Commands

```bash
pio test -e native            # run protocol unit tests on the host (no board)
pio run -e uno                # compile for the Uno
pio run -e uno -t upload      # compile + flash the connected Uno
pio device monitor -b 115200  # watch the serial link
```

> **Windows note:** `pio test -e native` needs a host C/C++ compiler on `PATH`.
> On this machine that is the MSYS2 mingw64 toolchain, which is visible from a
> Git Bash / MSYS2 shell but **not** from a stock PowerShell - so run the native
> tests from Bash. The `uno` build/upload/monitor commands work from any shell
> because they use PlatformIO's own bundled AVR toolchain.

## Adding a capability

1. If it drives hardware, add a small driver (a future `lib/` or `src/` module)
   with a narrow interface.
2. Add a handler function in `handlers.cpp` that parses its arguments and calls
   the driver, replying via `ProtocolIO`.
3. Register it by adding one row to `KIVO_HANDLERS`.
4. Add the operation to `/protocol/README.md` and mirror the backend side.

Nothing else - the transport, parser, and dispatcher are untouched.

## Constraints to respect

- **No `String`.** Use fixed `char` buffers; `String` fragments the 2 KB heap.
- **No blocking `delay()`.** Keep handlers fast; the loop must stay cooperative.
- **Lines are ≤ 64 bytes.** Enforced by the protocol and the buffers.
