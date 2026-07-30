"""An in-memory transport that emulates Kivo firmware.

This is not a mock with canned strings — it decodes real frames with the real
codec and produces real, CRC-valid responses, so it exercises the entire
protocol stack. It lets the backend be developed, demoed, and tested with no
Arduino attached (``kivo ping --fake``), and it doubles as an executable
reference for how the firmware is expected to behave.

The set of operations it understands mirrors the firmware handlers. Keep it in
sync as capabilities are added.
"""

from __future__ import annotations

from collections import deque

from ..protocol import codec
from ..protocol.errors import ErrorCode, ProtocolError
from ..protocol.messages import EVENT_ID, Frame, FrameType
from ..protocol.names import EventName, Operation, Payload, Status
from .base import Transport

# Mirrors firmware/src/config.h. The fake reports the same identity and screen
# geometry the real device would, so code paths behave identically either way.
_FW_NAME = "Kivo"
_FW_VERSION = "0.1.0"
_PROTO_VERSION = "1"
_LCD_COLS = 16
_LCD_ROWS = 2


class FakeTransport(Transport):
    """A software stand-in that behaves like the Kivo firmware over serial."""

    def __init__(self, *, emit_ready: bool = True) -> None:
        self._outbox: deque[str] = deque()
        self._open = False
        self._emit_ready = emit_ready
        self._screen = self._blank_screen()

    @property
    def resets_on_connect(self) -> bool:
        # The fake emulates a fresh boot on open (it emits READY), mirroring the
        # real Uno's auto-reset so both exercise the same connect handshake.
        return self._emit_ready

    def open(self) -> None:
        self._open = True
        self._screen = self._blank_screen()  # a fresh boot starts with a clear screen
        if self._emit_ready:
            self._emit_event(
                EventName.READY, f"{_FW_NAME} {_FW_VERSION} {_PROTO_VERSION}"
            )

    @property
    def screen(self) -> list[str]:
        """The emulated LCD contents, one string per row. For inspection in tests."""
        return list(self._screen)

    def close(self) -> None:
        self._open = False
        self._outbox.clear()

    def write_line(self, line: str) -> None:
        if not self._open:
            raise RuntimeError("transport is not open")
        self._handle_incoming(line)

    def read_line(self, timeout: float | None) -> str | None:
        # Responses are produced synchronously on write, so anything the device
        # would say is already queued. An empty outbox means "nothing to read".
        if self._outbox:
            return self._outbox.popleft()
        return None

    # -- firmware emulation ---------------------------------------------------

    def _handle_incoming(self, line: str) -> None:
        try:
            frame = codec.decode(line)
        except ProtocolError as exc:
            # Frame-level failure: cannot be correlated, reported as an event.
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
        else:
            self._respond_err(cmd.id, ErrorCode.UNKNOWN_OP, "unknown_op")

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
        # Overwrite in place, truncating at the row's right edge (as the device does).
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
        self._outbox.append(codec.encode(frame))
