"""The transport port: how the backend moves protocol lines to/from a device.

A transport knows nothing about Kivo semantics — only how to send and receive
lines of text. This narrow interface is what lets the real serial link and the
in-memory fake be used interchangeably, which in turn makes the whole backend
testable and runnable with no hardware attached.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType


class Transport(ABC):
    """A bidirectional, line-oriented byte channel to a device.

    Implementations are blocking with timeouts (see ADR-0004). Lines are passed
    without their trailing newline; the transport is responsible for adding it on
    send and stripping it on receive.
    """

    @property
    def resets_on_connect(self) -> bool:
        """Whether opening this transport reboots the device.

        When true, the device restarts on :meth:`open` and announces itself with
        a ``READY`` event; the client should wait for that event before sending
        commands (otherwise early commands are lost to the bootloader). The Uno
        does this via serial auto-reset; a hypothetical always-on link would not.
        Defaults to ``False``; adapters override as appropriate.
        """
        return False

    @abstractmethod
    def open(self) -> None:
        """Open the channel. Idempotent implementations are encouraged."""

    @abstractmethod
    def close(self) -> None:
        """Close the channel and release resources."""

    @abstractmethod
    def write_line(self, line: str) -> None:
        """Send one line (a newline is appended by the transport)."""

    @abstractmethod
    def read_line(self, timeout: float | None) -> str | None:
        """Read one line without its terminator.

        Blocks up to ``timeout`` seconds (``None`` = block indefinitely).
        Returns the line, or ``None`` if the timeout elapsed with no complete
        line available.
        """

    # -- context-manager sugar so callers can `with transport: ...` -----------

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
