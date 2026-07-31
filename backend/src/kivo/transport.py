"""Transport adapters for the Kivo device link.

A transport is a bidirectional, line-oriented byte channel that knows nothing
about Kivo semantics — only how to send and receive lines of text. That narrow
interface lets the real serial link and the in-memory fake be used
interchangeably, which makes the whole backend testable with no hardware.

* :class:`Transport` — the abstract port.
* :class:`SerialTransport` — the real ELEGOO Uno over USB serial.
* :class:`FakeTransport` — an in-memory firmware emulator for offline dev/tests.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import deque
from types import TracebackType

from . import protocol
from .protocol import (
    EVENT_ID,
    ErrorCode,
    EventName,
    Frame,
    FrameType,
    Operation,
    Payload,
    ProtocolError,
    Status,
    TransportError,
)

#: Default serial line speed. Must match the firmware (``KIVO_BAUD``).
DEFAULT_BAUD = 115200

_READ_CHUNK = 64  # bytes; matches the protocol max line length
_POLL_INTERVAL = 0.05  # seconds; granularity while waiting for a full line


class Transport(ABC):
    """A bidirectional, line-oriented byte channel to a device.

    Implementations are blocking with timeouts (ADR-0004). Lines are passed
    without their trailing newline; the transport adds it on send and strips it
    on receive.
    """

    @property
    def resets_on_connect(self) -> bool:
        """Whether opening this transport reboots the device.

        When true, the device restarts on :meth:`open` and announces itself with
        a ``READY`` event; the client should await that before sending commands
        (else early commands are lost to the bootloader).
        """
        return False

    @abstractmethod
    def open(self) -> None:
        """Open the channel."""

    @abstractmethod
    def close(self) -> None:
        """Close the channel and release resources."""

    @abstractmethod
    def write_line(self, line: str) -> None:
        """Send one line (a newline is appended by the transport)."""

    @abstractmethod
    def read_line(self, timeout: float | None) -> str | None:
        """Read one line without its terminator, blocking up to ``timeout``
        seconds (``None`` = forever). ``None`` if the timeout elapsed."""

    def __enter__(self) -> "Transport":
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class SerialTransport(Transport):
    """Line transport over a serial port using pyserial (imported lazily)."""

    def __init__(self, port: str, baud: int = DEFAULT_BAUD) -> None:
        self._port = port
        self._baud = baud
        self._serial = None  # set on open()
        self._buffer = bytearray()

    @property
    def resets_on_connect(self) -> bool:
        # Opening the port asserts DTR, which auto-resets the Uno; the firmware
        # then emits READY. See DeviceClient.connect().
        return True

    def open(self) -> None:
        if self._serial is not None:
            return
        try:
            import serial  # pyserial
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "pyserial is required for SerialTransport. Install it with "
                "`pip install pyserial` (or use FakeTransport for offline work)."
            ) from exc
        # A short read timeout lets read_line() poll toward its own deadline
        # rather than blocking on the OS call.
        try:
            self._serial = serial.Serial(self._port, self._baud, timeout=_POLL_INTERVAL)
        except serial.SerialException as exc:
            raise TransportError(
                f"could not open {self._port}: {exc}. Check the port is correct, "
                "the device is plugged in, and no other program (e.g. a running "
                "'kivo run', a serial monitor) is using it."
            ) from exc

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None
        self._buffer.clear()

    def write_line(self, line: str) -> None:
        if self._serial is None:
            raise RuntimeError("transport is not open")
        self._serial.write((line + "\n").encode("ascii"))
        self._serial.flush()

    def read_line(self, timeout: float | None) -> str | None:
        if self._serial is None:
            raise RuntimeError("transport is not open")
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            line = self._pop_buffered_line()
            if line is not None:
                return line
            if deadline is not None and time.monotonic() >= deadline:
                return None
            chunk = self._serial.read(_READ_CHUNK)
            if chunk:
                self._buffer.extend(chunk)

    def _pop_buffered_line(self) -> str | None:
        newline = self._buffer.find(b"\n")
        if newline == -1:
            return None
        raw = self._buffer[:newline]
        del self._buffer[: newline + 1]
        return raw.decode("ascii", errors="replace").rstrip("\r")


# Emulator identity + geometry. Mirrors firmware/src/config.h so the fake reports
# exactly what the real device would. "presence" is digital (0/1); "distance" is
# centimetres to the nearest object (starts far).
_FW_NAME = "Kivo"
_FW_VERSION = "0.1.0"
_PROTO_VERSION = "1"
_LCD_COLS = 16
_LCD_ROWS = 2
_INITIAL_SENSORS = {"light": 512, "presence": 0, "distance": 200}


class FakeTransport(Transport):
    """A software stand-in that behaves like the Kivo firmware over serial.

    Not a mock with canned strings — it decodes real frames with the real codec
    and produces real, CRC-valid responses, exercising the whole protocol stack.
    Keep the operations it understands in sync with the firmware handlers.
    """

    def __init__(self, *, emit_ready: bool = True) -> None:
        self._outbox: deque[str] = deque()
        self._open = False
        self._emit_ready = emit_ready
        self._screen = self._blank_screen()
        self._sensors: dict[str, int] = dict(_INITIAL_SENSORS)
        self._subscribed: set[str] = set()
        self.led: tuple[int, int, int] = (0, 0, 0)  # last RGB set (for tests)
        self.tones: list[tuple[int, int]] = []  # (freq, ms) played (for tests)

    @property
    def resets_on_connect(self) -> bool:
        return self._emit_ready

    def open(self) -> None:
        self._open = True
        self._screen = self._blank_screen()
        self._subscribed.clear()  # a reboot drops all subscriptions
        if self._emit_ready:
            self._emit_event(
                EventName.READY, f"{_FW_NAME} {_FW_VERSION} {_PROTO_VERSION}"
            )

    @property
    def screen(self) -> list[str]:
        """The emulated LCD contents, one string per row. For inspection in tests."""
        return list(self._screen)

    def set_sensor(self, name: str, value: int) -> None:
        """Change a sensor's value; if subscribed, emit a SENSOR event (how tests
        simulate the device streaming a changed reading)."""
        self._sensors[name] = value
        if name in self._subscribed:
            self._emit_event(EventName.SENSOR, f"{name} {value}")

    def close(self) -> None:
        self._open = False
        self._outbox.clear()

    def write_line(self, line: str) -> None:
        if not self._open:
            raise RuntimeError("transport is not open")
        self._handle_incoming(line)

    def read_line(self, timeout: float | None) -> str | None:
        # Responses are produced synchronously on write, so anything the device
        # would say is already queued. Empty outbox means "nothing to read".
        if self._outbox:
            return self._outbox.popleft()
        return None

    # -- firmware emulation ---------------------------------------------------

    def _handle_incoming(self, line: str) -> None:
        try:
            frame = protocol.decode(line)
        except ProtocolError as exc:
            code = ErrorCode.CRC_FAIL if "CRC" in str(exc) else ErrorCode.MALFORMED
            self._emit_event("ERROR", f"{int(code)} {code.name.lower()}")
            return
        if frame.type is not FrameType.CMD:
            return  # devices ignore anything that is not a command
        self._dispatch(frame)

    def _dispatch(self, cmd: Frame) -> None:
        op, _, args = cmd.body.partition(" ")
        if op == Operation.PING:
            self._respond_ok(cmd.id, Payload.PONG)
        elif op == Operation.IDENTIFY:
            self._respond_ok(cmd.id, f"{_FW_NAME} {_FW_VERSION} {_PROTO_VERSION}")
        elif op == Operation.DISPLAY_WRITE:
            self._display_write(cmd.id, args)
        elif op == Operation.DISPLAY_CLEAR:
            self._screen = self._blank_screen()
            self._respond_ok(cmd.id)
        elif op == Operation.SENSOR_READ:
            self._sensor_read(cmd.id, args)
        elif op == Operation.SENSOR_SUBSCRIBE:
            self._sensor_subscribe(cmd.id, args)
        elif op == Operation.SENSOR_UNSUBSCRIBE:
            self._sensor_unsubscribe(cmd.id, args)
        elif op == Operation.LED_SET:
            self._led_set(cmd.id, args)
        elif op == Operation.TONE_PLAY:
            self._tone_play(cmd.id, args)
        else:
            self._respond_err(cmd.id, ErrorCode.UNKNOWN_OP, "unknown_op")

    def _led_set(self, cmd_id: int, args: str) -> None:
        parts = args.split(" ")
        if len(parts) != 3 or not all(p in ("0", "1") for p in parts):
            self._respond_err(cmd_id, ErrorCode.BAD_ARGS, "bad_args")
            return
        self.led = (int(parts[0]), int(parts[1]), int(parts[2]))
        self._respond_ok(cmd_id)

    def _tone_play(self, cmd_id: int, args: str) -> None:
        freq_str, _, ms_str = args.partition(" ")
        try:
            self.tones.append((int(freq_str), int(ms_str)))
        except ValueError:
            self._respond_err(cmd_id, ErrorCode.BAD_ARGS, "bad_args")
            return
        self._respond_ok(cmd_id)

    def _sensor_read(self, cmd_id: int, name: str) -> None:
        if name not in self._sensors:
            self._respond_err(cmd_id, ErrorCode.BAD_ARGS, "bad_args")
            return
        self._respond_ok(cmd_id, str(self._sensors[name]))

    def _sensor_subscribe(self, cmd_id: int, name: str) -> None:
        if name not in self._sensors:
            self._respond_err(cmd_id, ErrorCode.BAD_ARGS, "bad_args")
            return
        self._subscribed.add(name)
        self._respond_ok(cmd_id)
        self._emit_event(EventName.SENSOR, f"{name} {self._sensors[name]}")

    def _sensor_unsubscribe(self, cmd_id: int, name: str) -> None:
        if name not in self._sensors:
            self._respond_err(cmd_id, ErrorCode.BAD_ARGS, "bad_args")
            return
        self._subscribed.discard(name)
        self._respond_ok(cmd_id)

    def _display_write(self, cmd_id: int, args: str) -> None:
        row_str, _, rest = args.partition(" ")
        col_str, _, text = rest.partition(" ")
        try:
            row, col = int(row_str), int(col_str)
        except ValueError:
            self._respond_err(cmd_id, ErrorCode.BAD_ARGS, "bad_args")
            return
        if not (0 <= row < _LCD_ROWS and 0 <= col < _LCD_COLS):
            self._respond_err(cmd_id, ErrorCode.BAD_ARGS, "bad_args")
            return
        chars = list(self._screen[row])
        for offset, char in enumerate(text):
            if col + offset >= _LCD_COLS:
                break
            chars[col + offset] = char
        self._screen[row] = "".join(chars)
        self._respond_ok(cmd_id)

    @staticmethod
    def _blank_screen() -> list[str]:
        return [" " * _LCD_COLS for _ in range(_LCD_ROWS)]

    def _respond_ok(self, cmd_id: int, data: str = "") -> None:
        body = Status.OK if not data else f"{Status.OK} {data}"
        self._send(Frame(FrameType.RES, cmd_id, body))

    def _respond_err(self, cmd_id: int, code: ErrorCode, message: str) -> None:
        self._send(Frame(FrameType.RES, cmd_id, f"{Status.ERR} {int(code)} {message}"))

    def _emit_event(self, name: str, data: str = "") -> None:
        body = name if not data else f"{name} {data}"
        self._send(Frame(FrameType.EVT, EVENT_ID, body))

    def _send(self, frame: Frame) -> None:
        self._outbox.append(protocol.encode(frame))
