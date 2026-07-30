"""Serial transport for a physically-connected Kivo device (the ELEGOO Uno).

Thin wrapper over pyserial that presents the line-oriented :class:`Transport`
interface. ``pyserial`` is imported lazily so the rest of the backend (and the
test suite, which uses the fake transport) does not require it to be installed.
"""

from __future__ import annotations

import time

from .base import Transport

#: Default serial line speed. Must match the firmware (``KIVO_BAUD`` in
#: ``firmware/src/config.h``); the wire baud is a physical property of the link.
DEFAULT_BAUD = 115200

_READ_CHUNK = 64  # bytes; matches the protocol max line length
_POLL_INTERVAL = 0.05  # seconds; granularity while waiting for a full line


class SerialTransport(Transport):
    """Line transport over a serial port using pyserial."""

    def __init__(self, port: str, baud: int = DEFAULT_BAUD) -> None:
        self._port = port
        self._baud = baud
        self._serial = None  # set on open(); typed loosely to avoid a hard import
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
        # A short read timeout lets read_line() poll cooperatively toward its
        # own deadline rather than blocking on the OS call.
        self._serial = serial.Serial(self._port, self._baud, timeout=_POLL_INTERVAL)

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
        """Extract one complete line from the read buffer, if present."""
        newline = self._buffer.find(b"\n")
        if newline == -1:
            return None
        raw = self._buffer[:newline]
        del self._buffer[: newline + 1]
        return raw.decode("ascii", errors="replace").rstrip("\r")
