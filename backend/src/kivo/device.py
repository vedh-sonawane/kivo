"""The device capability layer - the backend's high-level handle on Kivo.

:class:`DeviceClient` turns capability calls (``ping()``, ``display_write(...)``,
``sensor_read(...)``) into protocol commands, sends them over a
:class:`Transport`, and correlates the matching response. Unsolicited events are
drained while waiting and handed to an optional callback, so a ``READY`` on reset
or a sensor event is never lost or mistaken for a response.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType

from .protocol import (
    Command,
    DeviceError,
    Event,
    EventName,
    Frame,
    FrameType,
    Operation,
    Payload,
    ProtocolError,
    Response,
    TransportTimeout,
    decode,
    encode,
)
from .transport import Transport

_SENSOR_EVENT_FIELDS = 2  # "<name> <value>"

_log = logging.getLogger(__name__)

# id 0 is reserved for events, so host correlation ids run 1..65535 and wrap.
_MIN_ID = 1
_MAX_ID = 0xFFFF

# Defaults (seconds). Overridable per client; the CLI sources them from Settings.
DEFAULT_RESPONSE_TIMEOUT = 2.0
DEFAULT_READY_TIMEOUT = 5.0

EventHandler = Callable[[Event], None]


@dataclass(frozen=True, slots=True)
class Identity:
    """Who the device is and what protocol it speaks (from ``READY``/IDENTIFY)."""

    name: str
    version: str
    protocol: int


@dataclass(frozen=True, slots=True)
class SensorReading:
    """A single sensor sample, parsed from a ``SENSOR`` event or a read."""

    name: str
    value: int


class DeviceClient:
    """Send capability commands to a Kivo device and receive correlated replies."""

    def __init__(
        self,
        transport: Transport,
        *,
        response_timeout: float = DEFAULT_RESPONSE_TIMEOUT,
        ready_timeout: float = DEFAULT_READY_TIMEOUT,
        event_handler: EventHandler | None = None,
    ) -> None:
        self._transport = transport
        self._response_timeout = response_timeout
        self._ready_timeout = ready_timeout
        self._event_handler = event_handler
        self._last_id = 0
        self._identity: Identity | None = None

    # -- lifecycle ------------------------------------------------------------

    def connect(self) -> None:
        """Open the link and, if the device reboots on connect, await ``READY``.

        Waiting for the boot handshake prevents the first command from being
        swallowed by the Uno's bootloader after the serial auto-reset.
        """
        self._transport.open()
        if self._transport.resets_on_connect:
            self.wait_for_ready()

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> "DeviceClient":
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def identity(self) -> Identity | None:
        """The identity learned from the last ``READY`` or ``identify()``."""
        return self._identity

    # -- capabilities ---------------------------------------------------------

    def ping(self) -> None:
        """Round-trip liveness check. Raises on failure or timeout."""
        response = self.request(Operation.PING)
        if response.data != Payload.PONG:
            raise ProtocolError(f"unexpected PING payload: {response.data!r}")

    def identify(self) -> Identity:
        """Ask the device who it is."""
        response = self.request(Operation.IDENTIFY)
        self._identity = self._parse_identity(response.data)
        return self._identity

    def display_write(self, text: str, *, row: int = 0, col: int = 0) -> None:
        """Write ``text`` on the LCD at ``(row, col)`` (both default to 0)."""
        self.request(Operation.DISPLAY_WRITE, f"{row} {col} {text}")

    def display_clear(self) -> None:
        """Clear the LCD."""
        self.request(Operation.DISPLAY_CLEAR)

    def led_set(self, r: int, g: int, b: int) -> None:
        """Set the RGB LED. Each channel is 0 (off) or 1 (on) - the device does
        digital colour, so the host mixes from the 7 primaries."""
        self.request(Operation.LED_SET, f"{r} {g} {b}")

    def tone_play(self, freq: int, ms: int) -> None:
        """Play a tone of ``freq`` Hz for ``ms`` milliseconds (non-blocking on the
        device). ``freq`` 0 stops any tone."""
        self.request(Operation.TONE_PLAY, f"{freq} {ms}")

    def servo_set(self, angle: int) -> None:
        """Move the servo to ``angle`` degrees (0-180). The host sequences a
        gesture from a series of these; the device just holds the last angle."""
        self.request(Operation.SERVO_SET, str(angle))

    def sensor_read(self, name: str) -> SensorReading:
        """One-shot read of a named sensor. Raises on an unknown sensor."""
        response = self.request(Operation.SENSOR_READ, name)
        try:
            return SensorReading(name=name, value=int(response.data))
        except ValueError as exc:
            raise ProtocolError(f"non-integer sensor value: {response.data!r}") from exc

    def subscribe_sensor(self, name: str) -> None:
        """Ask the device to start streaming ``name`` as ``SENSOR`` events."""
        self.request(Operation.SENSOR_SUBSCRIBE, name)

    def unsubscribe_sensor(self, name: str) -> None:
        """Ask the device to stop streaming ``name``."""
        self.request(Operation.SENSOR_UNSUBSCRIBE, name)

    # -- events / streaming ---------------------------------------------------

    def set_event_handler(self, handler: EventHandler | None) -> None:
        """Set (or clear) the callback invoked for every unsolicited event."""
        self._event_handler = handler

    def pump_events(self, timeout: float = 0.0) -> None:
        """Drain and dispatch any events currently available, then return."""
        while True:
            frame = self._read_frame(timeout)
            if frame is None:
                return
            if frame.type is FrameType.EVT:
                self._handle_event(Event.from_frame(frame))
            else:
                _log.debug("ignoring %r while pumping events", frame)

    def listen(self) -> None:
        """Block forever, dispatching events to the handler (e.g. ``kivo watch``)."""
        while True:
            frame = self._read_frame(self._response_timeout)
            if frame is None:
                continue
            if frame.type is FrameType.EVT:
                self._handle_event(Event.from_frame(frame))
            else:
                _log.debug("ignoring %r while listening", frame)

    @staticmethod
    def parse_sensor_event(event: Event) -> SensorReading | None:
        """Parse a ``SENSOR`` event into a reading, or ``None`` if it isn't one."""
        if event.name != EventName.SENSOR:
            return None
        parts = event.data.split(" ")
        if len(parts) != _SENSOR_EVENT_FIELDS:
            raise ProtocolError(f"malformed SENSOR event: {event.data!r}")
        name, value = parts
        try:
            return SensorReading(name=name, value=int(value))
        except ValueError as exc:
            raise ProtocolError(f"non-integer sensor value: {value!r}") from exc

    def wait_for_ready(self, timeout: float | None = None) -> Identity | None:
        """Consume events until a ``READY`` arrives; return the device identity."""
        budget = self._ready_timeout if timeout is None else timeout
        deadline = time.monotonic() + budget
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            frame = self._read_frame(remaining)
            if frame is None:
                _log.warning("no READY within %.1fs; continuing anyway", budget)
                return None
            if frame.type is FrameType.EVT:
                event = Event.from_frame(frame)
                self._handle_event(event)
                if event.name == EventName.READY:
                    self._identity = self._parse_identity(event.data)
                    return self._identity
            else:
                _log.debug("ignoring %r while waiting for READY", frame)

    # -- request/response core ------------------------------------------------

    def request(self, op: str, args: str = "") -> Response:
        """Send a command and return its successful response, raising on error."""
        response = self.send(op, args)
        if not response.ok:
            raise DeviceError(response.error_code or 0, response.error_message)
        return response

    def send(self, op: str, args: str = "") -> Response:
        """Send a command and return the response (success *or* error)."""
        command = Command(id=self._next_id(), op=op, args=args)
        line = encode(Frame(FrameType.CMD, command.id, command.body))
        _log.debug("-> %s", line)
        self._transport.write_line(line)
        return self._await_response(command.id)

    def _await_response(self, expected_id: int) -> Response:
        while True:
            frame = self._read_frame(self._response_timeout)
            if frame is None:
                raise TransportTimeout(
                    f"no response to command id {expected_id} within "
                    f"{self._response_timeout}s"
                )
            if frame.type is FrameType.EVT:
                self._handle_event(Event.from_frame(frame))
                continue
            if frame.type is FrameType.RES and frame.id == expected_id:
                return Response.from_frame(frame)
            _log.debug("ignoring uncorrelated frame: %r", frame)

    def _read_frame(self, timeout: float | None) -> Frame | None:
        """Read and decode one frame, skipping undecodable lines; ``None`` on timeout."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            line = self._transport.read_line(remaining)
            if line is None:
                return None
            _log.debug("<- %s", line)
            try:
                return decode(line)
            except ProtocolError as exc:
                _log.warning("discarding undecodable line %r: %s", line, exc)
                continue

    def _handle_event(self, event: Event) -> None:
        _log.info("event: %s %s", event.name, event.data)
        if self._event_handler is not None:
            self._event_handler(event)

    @staticmethod
    def _parse_identity(data: str) -> Identity:
        parts = data.split(" ")
        if len(parts) != 3:
            raise ProtocolError(f"malformed identity payload: {data!r}")
        name, version, proto = parts
        try:
            protocol = int(proto)
        except ValueError as exc:
            raise ProtocolError(f"invalid protocol version {proto!r}") from exc
        return Identity(name=name, version=version, protocol=protocol)

    def _next_id(self) -> int:
        self._last_id = _MIN_ID if self._last_id >= _MAX_ID else self._last_id + 1
        return self._last_id
