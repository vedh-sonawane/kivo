"""Kivo Serial Protocol — host-side implementation of ``/protocol/README.md``.

Framing + integrity (``codec``, ``crc8``) are separated from message semantics
(``messages``). Callers in the ``device`` layer work with :class:`Command`,
:class:`Response`, and :class:`Event`; the transport layer works with wire lines.
"""

from .codec import MAX_LINE_BYTES, decode, encode
from .crc8 import crc8, crc8_hex
from .errors import (
    DeviceError,
    ErrorCode,
    ProtocolError,
    TransportTimeout,
)
from .messages import EVENT_ID, Command, Event, Frame, FrameType, Response
from .names import EventName, Operation, Payload, Status

__all__ = [
    "MAX_LINE_BYTES",
    "decode",
    "encode",
    "crc8",
    "crc8_hex",
    "DeviceError",
    "ErrorCode",
    "ProtocolError",
    "TransportTimeout",
    "EVENT_ID",
    "Command",
    "Event",
    "Frame",
    "FrameType",
    "Response",
    "EventName",
    "Operation",
    "Payload",
    "Status",
]
