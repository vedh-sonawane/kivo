"""Protocol-level error types and the shared error-code enumeration.

The numeric codes mirror the table in ``/protocol/README.md`` (§5.2 and §8) and
must stay in sync with the firmware.
"""

from __future__ import annotations

import enum


class ErrorCode(enum.IntEnum):
    """Error codes carried on the wire.

    1 and 2 are frame-level failures reported as ``EVT 0 ERROR``; the rest are
    operation-level failures reported as ``RES <id> ERR``.
    """

    CRC_FAIL = 1
    MALFORMED = 2
    UNKNOWN_OP = 3
    BAD_ARGS = 4
    BUSY = 5
    INTERNAL = 6


class ProtocolError(Exception):
    """A frame could not be decoded (bad framing, bad CRC, malformed fields)."""


class DeviceError(Exception):
    """The device returned a ``RES ... ERR`` for a command.

    Carries the structured error code and message the device reported.
    """

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        try:
            name = ErrorCode(code).name
        except ValueError:
            name = f"CODE_{code}"
        super().__init__(f"device error {code} ({name}): {message}")


class TransportTimeout(Exception):
    """No response arrived within the allotted time."""
