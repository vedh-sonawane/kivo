"""Protocol vocabulary — the operation names, event names, and status tokens
defined by ``/protocol/README.md``.

These strings appear in several modules (the codec, the device client, the
firmware emulator). Defining them once here prevents typo-drift and gives a
single place to see everything the protocol speaks. The firmware maintains its
own mirror (``firmware/src/protocol_vocab.h``); the shared spec is the contract
that keeps the two in step.
"""

from __future__ import annotations


class Operation:
    """Command operation names (host -> device)."""

    PING = "PING"
    IDENTIFY = "SYS.IDENTIFY"
    DISPLAY_WRITE = "DISPLAY.WRITE"
    DISPLAY_CLEAR = "DISPLAY.CLEAR"


class EventName:
    """Unsolicited event names (device -> host)."""

    READY = "READY"
    ERROR = "ERROR"


class Status:
    """The first token of a ``RES`` body."""

    OK = "OK"
    ERR = "ERR"


class Payload:
    """Fixed response payloads."""

    PONG = "PONG"
