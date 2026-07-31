"""Kivo Serial Protocol — host-side implementation of ``/protocol/README.md``.

One module covering the whole wire protocol: CRC-8 integrity, error types, the
vocabulary (operation/event/status names), typed messages, and the codec that
frames them. The firmware mirrors this contract in ``firmware/``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

# -- CRC-8 (poly 0x07, init 0x00, "CRC-8/SMBUS"); must match the firmware -----

_POLYNOMIAL = 0x07


def crc8(data: bytes) -> int:
    """Return the CRC-8 of ``data`` as an integer 0..255."""
    crc = 0x00
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ _POLYNOMIAL) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def crc8_hex(data: bytes) -> str:
    """Return the CRC-8 of ``data`` as two uppercase hex digits (e.g. ``"A3"``)."""
    return f"{crc8(data):02X}"


# -- errors ------------------------------------------------------------------


class ErrorCode(enum.IntEnum):
    """Wire error codes (mirrors ``/protocol/README.md`` §5.2 and §8).

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
    """The device returned a ``RES ... ERR`` for a command."""

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


class TransportError(Exception):
    """The transport could not be opened or used (e.g. port missing or busy)."""


# -- vocabulary (mirrored by the handler registry in firmware/src/kivo.cpp) --


class Operation:
    """Command operation names (host -> device)."""

    PING = "PING"
    IDENTIFY = "SYS.IDENTIFY"
    DISPLAY_WRITE = "DISPLAY.WRITE"
    DISPLAY_CLEAR = "DISPLAY.CLEAR"
    SENSOR_READ = "SENSOR.READ"
    SENSOR_SUBSCRIBE = "SENSOR.SUBSCRIBE"
    SENSOR_UNSUBSCRIBE = "SENSOR.UNSUBSCRIBE"
    LED_SET = "LED.SET"
    TONE_PLAY = "TONE.PLAY"


class EventName:
    """Unsolicited event names (device -> host)."""

    READY = "READY"
    ERROR = "ERROR"
    SENSOR = "SENSOR"


class Status:
    """The first token of a ``RES`` body."""

    OK = "OK"
    ERR = "ERR"


class Payload:
    """Fixed response payloads."""

    PONG = "PONG"


# -- messages ----------------------------------------------------------------


class FrameType(enum.Enum):
    CMD = "CMD"
    RES = "RES"
    EVT = "EVT"


# Events always carry this id; see /protocol/README.md §5.3.
EVENT_ID = 0


@dataclass(frozen=True, slots=True)
class Frame:
    """A decoded frame with an opaque body. No operation semantics attached."""

    type: FrameType
    id: int
    body: str


@dataclass(frozen=True, slots=True)
class Command:
    """A host → device request."""

    id: int
    op: str
    args: str = ""

    @property
    def body(self) -> str:
        return self.op if not self.args else f"{self.op} {self.args}"


@dataclass(frozen=True, slots=True)
class Response:
    """A device → host reply. ``ok`` distinguishes success from failure."""

    id: int
    ok: bool
    data: str = ""
    error_code: int | None = None
    error_message: str = ""

    @classmethod
    def from_frame(cls, frame: Frame) -> "Response":
        if frame.type is not FrameType.RES:
            raise ProtocolError(f"expected RES frame, got {frame.type.value}")
        status, _, rest = frame.body.partition(" ")
        if status == Status.OK:
            return cls(id=frame.id, ok=True, data=rest)
        if status == Status.ERR:
            code_str, _, message = rest.partition(" ")
            try:
                code = int(code_str)
            except ValueError as exc:
                raise ProtocolError(f"invalid error code {code_str!r}") from exc
            return cls(id=frame.id, ok=False, error_code=code, error_message=message)
        raise ProtocolError(f"invalid response status {status!r}")


@dataclass(frozen=True, slots=True)
class Event:
    """An unsolicited device → host notification."""

    name: str
    data: str = ""

    @classmethod
    def from_frame(cls, frame: Frame) -> "Event":
        if frame.type is not FrameType.EVT:
            raise ProtocolError(f"expected EVT frame, got {frame.type.value}")
        name, _, data = frame.body.partition(" ")
        return cls(name=name, data=data)


# -- codec: frames <-> wire lines (grammar: `type SP id SP body "*" crc`) -----

#: Maximum wire-line length in bytes, excluding the terminator (firmware SRAM
#: budget; /protocol/README.md §3).
MAX_LINE_BYTES = 64

#: Reserved checksum separator; must not appear in a payload.
_CHECKSUM_SEP = "*"


def encode(frame: Frame) -> str:
    """Serialize a :class:`Frame` to a wire line (no trailing newline)."""
    if _CHECKSUM_SEP in frame.body:
        raise ProtocolError(
            f"body may not contain the reserved {_CHECKSUM_SEP!r} character: "
            f"{frame.body!r}"
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
    """Parse a wire line (no trailing newline) into a :class:`Frame`."""
    if len(line.encode("ascii", errors="replace")) > MAX_LINE_BYTES:
        raise ProtocolError(f"line exceeds {MAX_LINE_BYTES} bytes")

    payload, sep, crc = line.partition(_CHECKSUM_SEP)
    if not sep:
        raise ProtocolError(f"missing checksum separator in {line!r}")
    expected = crc8_hex(payload.encode("ascii"))
    if crc.upper() != expected:
        raise ProtocolError(f"CRC mismatch: got {crc!r}, expected {expected!r}")

    # "TYPE id body..." — split into three so a body with spaces stays intact.
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
