"""Typed representations of Kivo Serial Protocol messages.

Two levels are modelled:

* :class:`Frame` is the low-level, semantics-free view the codec produces:
  a ``type``, a correlation ``id``, and an opaque ``body`` string. The codec
  (``codec.py``) owns framing and CRC and knows nothing beyond this.

* :class:`Command`, :class:`Response`, and :class:`Event` are the high-level,
  meaningful views the device layer works with. Helpers convert between a
  :class:`Frame` and these types.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from .errors import ProtocolError
from .names import Status


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
    """A device → host reply to a command.

    ``ok`` distinguishes success from failure. On success, ``data`` holds any
    operation-defined payload. On failure, ``error_code`` / ``error_message`` are
    populated instead.
    """

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
