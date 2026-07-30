"""Encode/decode Kivo Serial Protocol frames to and from wire lines.

This module owns framing and integrity only. It converts between a
:class:`~kivo.protocol.messages.Frame` and a single line of wire text
(without the trailing newline; the transport layer adds/strips that).

Grammar (see /protocol/README.md §4)::

    line = type SP id SP body "*" crc

The checksum covers everything before the ``*`` — i.e. ``type SP id SP body``.
"""

from __future__ import annotations

from .crc8 import crc8_hex
from .errors import ProtocolError
from .messages import Frame, FrameType

#: Maximum wire-line length in bytes, excluding the line terminator
#: (matches the firmware SRAM budget; /protocol/README.md §3).
MAX_LINE_BYTES = 64

#: Reserved checksum separator; must not appear in a payload.
_CHECKSUM_SEP = "*"


def encode(frame: Frame) -> str:
    """Serialize a :class:`Frame` to a wire line (no trailing newline).

    Raises :class:`ProtocolError` if the result would exceed the line budget or
    if the body contains the reserved ``*`` byte.
    """
    if _CHECKSUM_SEP in frame.body:
        raise ProtocolError(
            f"body may not contain the reserved {_CHECKSUM_SEP!r} character: {frame.body!r}"
        )
    if not 0 <= frame.id <= 0xFFFF:
        raise ProtocolError(f"id out of range 0..65535: {frame.id}")

    payload = f"{frame.type.value} {frame.id} {frame.body}"
    line = f"{payload}{_CHECKSUM_SEP}{crc8_hex(payload.encode('ascii'))}"

    if len(line.encode("ascii")) > MAX_LINE_BYTES:
        raise ProtocolError(
            f"encoded line is {len(line)} bytes, exceeds {MAX_LINE_BYTES}: {line!r}"
        )
    return line


def decode(line: str) -> Frame:
    """Parse a wire line (no trailing newline) into a :class:`Frame`.

    Verifies the CRC and the frame structure. Raises :class:`ProtocolError` on
    any framing, checksum, or field error.
    """
    if len(line.encode("ascii", errors="replace")) > MAX_LINE_BYTES:
        raise ProtocolError(f"line exceeds {MAX_LINE_BYTES} bytes")

    payload, sep, crc = line.partition(_CHECKSUM_SEP)
    if not sep:
        raise ProtocolError(f"missing checksum separator in {line!r}")
    expected = crc8_hex(payload.encode("ascii"))
    if crc.upper() != expected:
        raise ProtocolError(f"CRC mismatch: got {crc!r}, expected {expected!r}")

    # payload = "TYPE id body..."; split into exactly three parts so the body
    # (which may contain spaces) is preserved intact.
    parts = payload.split(" ", 2)
    if len(parts) < 2:
        raise ProtocolError(f"malformed frame: {payload!r}")
    type_str, id_str = parts[0], parts[1]
    body = parts[2] if len(parts) == 3 else ""

    try:
        frame_type = FrameType(type_str)
    except ValueError as exc:
        raise ProtocolError(f"unknown frame type {type_str!r}") from exc
    try:
        frame_id = int(id_str)
    except ValueError as exc:
        raise ProtocolError(f"invalid id {id_str!r}") from exc

    return Frame(type=frame_type, id=frame_id, body=body)
