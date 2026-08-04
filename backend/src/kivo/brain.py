"""Kivo's Brain - the persistent, autonomous host-side mind.

A :class:`Brain` owns one long-lived device connection, keeps a
:class:`WorldState`, and runs pure :class:`Behavior`s that return
:class:`Action`s (``ShowText`` / ``ClearScreen``) which it applies to the device.
Behaviours are pure (they never touch the device), so they're trivial to test.
Single-threaded (ADR-0004): events are queued and processed on the loop.

This one module holds the world model, the actions, the behaviour base + the
starter personality, the LCD marquee, and the Brain loop.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from .device import DeviceClient, SensorReading
from .protocol import DeviceError, ErrorCode, Event

if TYPE_CHECKING:
    from .vision import EmotionSource

_log = logging.getLogger(__name__)


# -- world state -------------------------------------------------------------


@dataclass
class WorldState:
    """Everything Kivo currently knows: the latest reading per sensor (for now)."""

    sensors: dict[str, int] = field(default_factory=dict)

    def update_sensor(self, reading: SensorReading) -> None:
        self.sensors[reading.name] = reading.value

    def sensor(self, name: str) -> int | None:
        """Latest value for a sensor, or ``None`` if never seen."""
        return self.sensors.get(name)


# -- actions: what a behaviour wants done, decoupled from how -----------------


@dataclass(frozen=True, slots=True)
class ShowText:
    """Show ``text`` on a display row (column 0)."""

    row: int
    text: str


@dataclass(frozen=True, slots=True)
class ClearScreen:
    """Blank the display."""


@dataclass(frozen=True, slots=True)
class SetColor:
    """Set the RGB LED. Each channel is 0 (off) or 1 (on) - digital colour."""

    r: int
    g: int
    b: int


@dataclass(frozen=True, slots=True)
class PlayTone:
    """Play a tone of ``freq`` Hz for ``ms`` ms on the buzzer (0 Hz = silence)."""

    freq: int
    ms: int


@dataclass(frozen=True, slots=True)
class SetServo:
    """Move the servo to ``angle`` degrees (0-180). Gestures are a series of these."""

    angle: int


# The set of things a behaviour can ask for. Extend as Kivo gains outputs.
Action = ShowText | ClearScreen | SetColor | PlayTone | SetServo


# -- behaviour base ----------------------------------------------------------


class Behavior:
    """One unit of Kivo's autonomous conduct. Pure: hooks return Actions.

    Subclass and override only the hooks you care about; unhandled hooks return
    no actions.
    """

    def on_start(self, world: WorldState) -> list[Action]:
        """Called once when the Brain wakes (e.g. to greet)."""
        return []

    def on_sensor(self, reading: SensorReading, world: WorldState) -> list[Action]:
        """Called for each sensor reading the device streams."""
        return []

    def on_tick(self, world: WorldState) -> list[Action]:
        """Called every Brain loop iteration, so a behaviour can emit actions on
        its own schedule (e.g. an async AI line that just became ready, or a
        time-based transition). Default: nothing."""
        return []


# -- LCD marquee -------------------------------------------------------------


class RowScroller:
    """Reveals a possibly-too-long line on a fixed-width row by scrolling left.

    The LCD is 16 columns but Kivo's lines are often longer. Rather than trim and
    lose words, the host keeps the whole line and slides it left one character at
    a time (looping with a small gap, a brief hold on the opening); only the
    visible 16-char window is ever sent to the device. A line that fits is shown
    static (padded to clear the row). Timing is in Brain ticks (one per loop).
    """

    _GAP = "   "  # blank run between the tail and the looped restart

    def __init__(
        self, width: int, *, step_ticks: int = 3, hold_ticks: int = 6
    ) -> None:
        self._width = width
        self._step_ticks = max(1, step_ticks)
        self._hold_ticks = max(0, hold_ticks)
        self._text = ""
        self._frame = 0  # how many characters we've shifted this cycle
        self._counter = 0  # raw tick counter, for the step cadence
        self._holding = 0  # remaining hold ticks at the start of a cycle

    def set(self, text: str) -> str:
        """Load a new line and return the window to show immediately."""
        self._text = text
        self._frame = 0
        self._counter = 0
        self._holding = self._hold_ticks if self.active else 0
        return self._render()

    @property
    def active(self) -> bool:
        """True when the text is longer than the row and therefore scrolls."""
        return len(self._text) > self._width

    def tick(self) -> str | None:
        """Advance one loop iteration; return the new window or ``None`` if
        nothing changed (line fits, or we're between shift steps)."""
        if not self.active:
            return None
        self._counter += 1
        if self._counter % self._step_ticks != 0:
            return None
        if self._frame == 0 and self._holding > 0:
            self._holding -= 1  # linger on the opening words
            return None
        span = len(self._text) + len(self._GAP)
        self._frame += 1
        if self._frame >= span:
            self._frame = 0
            self._holding = self._hold_ticks
        return self._render()

    def _render(self) -> str:
        if not self.active:
            return self._text.ljust(self._width)
        buf = self._text + self._GAP
        # Double the buffer so a window that wraps past the end reads cleanly.
        return (buf + buf)[self._frame : self._frame + self._width]


# -- classifiers / helpers ---------------------------------------------------


class LightClassifier:
    """Maps a raw light reading to dark / dim / bright, with **hysteresis**.

    Once in a band, a value must move a full ``margin`` past the threshold before
    the label switches, so noise near a boundary doesn't flap the label.
    """

    def __init__(
        self, *, dark_below: int = 300, bright_above: int = 700, margin: int = 40
    ) -> None:
        self._dark_below = dark_below
        self._bright_above = bright_above
        self._margin = margin
        self._label: str | None = None

    def classify(self, value: int) -> str:
        self._label = self._next(value)
        return self._label

    def _next(self, value: int) -> str:
        dark_line = self._dark_below
        bright_line = self._bright_above
        if self._label == "dark":
            dark_line += self._margin
        elif self._label == "bright":
            bright_line -= self._margin
        elif self._label == "dim":
            dark_line -= self._margin
            bright_line += self._margin
        if value < dark_line:
            return "dark"
        if value > bright_line:
            return "bright"
        return "dim"


class PresenceEstimator:
    """Fuses ultrasonic distance and PIR motion into a stable "is someone here?".

    Motion alone is unreliable - a still person (reading, resting, asleep) stops
    moving and a motion-only sensor decides they've gone. So presence is driven by
    *distance*: you are here while something sits within ``near_cm`` of the sensor.
    PIR motion only ever *adds* presence (it can't mark you gone), covering the
    moment you're just outside the ultrasonic's narrow cone.

    You are gone only once the distance is clearly beyond range (past
    ``near_cm + margin``, hysteresis) *and* no motion has been seen for
    ``motion_grace`` seconds. Being close never reads as gone.
    """

    def __init__(
        self,
        *,
        distance_sensor: str = "distance",
        motion_sensor: str = "presence",
        near_cm: int = 120,
        margin: int = 30,
        motion_grace: float = 8.0,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._distance_sensor = distance_sensor
        self._motion_sensor = motion_sensor
        self._near_cm = near_cm
        self._margin = margin
        self._motion_grace = motion_grace
        self._now = now or time.monotonic
        self._distance: int | None = None
        self._last_motion: float | None = None
        self._present = False

    def handles(self, sensor_name: str) -> bool:
        return sensor_name in (self._distance_sensor, self._motion_sensor)

    def feed(self, reading: SensorReading) -> None:
        if reading.name == self._distance_sensor:
            self._distance = reading.value
        elif reading.name == self._motion_sensor and reading.value >= 1:
            self._last_motion = self._now()

    def evaluate(self) -> bool:
        """Recompute presence. Call every tick, not only on new readings: a still
        scene emits nothing, so "far for a while -> gone" is clock-driven."""
        near_line = self._near_cm + (self._margin if self._present else 0)
        near = self._distance is not None and self._distance < near_line
        recent_motion = (
            self._last_motion is not None
            and (self._now() - self._last_motion) < self._motion_grace
        )
        self._present = near or recent_motion
        return self._present


class ProximityGate:
    """Binary "is the user leaning in close?" from an ultrasonic distance (cm),
    with hysteresis. Leaning in is a deliberate gesture, so Kivo reacts to it but
    not to sitting at normal desk range. Enters "close" below ``close_below``;
    won't leave until the distance grows past ``close_below + margin``."""

    def __init__(self, *, close_below: int = 20, margin: int = 10) -> None:
        self._close_below = close_below
        self._margin = margin
        self._close = False

    def update(self, distance_cm: int) -> bool:
        line = self._close_below + (self._margin if self._close else 0)
        self._close = distance_cm < line
        return self._close


def part_of_day(hour: int) -> str:
    """Coarse time-of-day bucket from a 0-23 hour."""
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


_TIME_GREETINGS = {
    "morning": "Good morning",
    "afternoon": "Good afternoon",
    "evening": "Good evening",
    "night": "Hi, night owl",
}


# -- starter personality -----------------------------------------------------


class Greeter(Behavior):
    """Shows a fixed greeting the moment Kivo wakes."""

    def __init__(self, message: str = "Hi, I'm Kivo", *, row: int = 0) -> None:
        self._message = message
        self._row = row

    def on_start(self, world: WorldState) -> list[Action]:
        return [ShowText(self._row, self._message)]


class TimeGreeter(Behavior):
    """Greets according to the time of day, so Kivo feels aware of *when* it is."""

    def __init__(
        self, *, row: int = 0, now: Callable[[], datetime] | None = None
    ) -> None:
        self._row = row
        self._now = now or datetime.now

    def on_start(self, world: WorldState) -> list[Action]:
        greeting = _TIME_GREETINGS[part_of_day(self._now().hour)]
        return [ShowText(self._row, greeting)]


class LightMood(Behavior):
    """Narrates the room's light level, updating only when it actually changes."""

    _LABELS = ("dark", "dim", "bright")
    _LABEL_WIDTH = max(len(label) for label in _LABELS)

    def __init__(
        self,
        *,
        sensor: str = "light",
        row: int = 1,
        dark_below: int = 300,
        bright_above: int = 700,
        margin: int = 40,
        prefix: str = "Room: ",
    ) -> None:
        self._sensor = sensor
        self._row = row
        self._prefix = prefix
        self._classifier = LightClassifier(
            dark_below=dark_below, bright_above=bright_above, margin=margin
        )
        self._last_label: str | None = None

    def on_sensor(self, reading: SensorReading, world: WorldState) -> list[Action]:
        if reading.name != self._sensor:
            return []
        label = self._classifier.classify(reading.value)
        if label == self._last_label:
            return []  # only speak when the mood actually changes
        self._last_label = label
        text = f"{self._prefix}{label:<{self._LABEL_WIDTH}}"
        return [ShowText(self._row, text)]


class PresenceGreeter(Behavior):
    """Greets when someone arrives and says goodbye only once they've truly left.

    Presence is the fused distance + motion estimate (see
    :class:`PresenceEstimator`), so sitting still up close still counts as here.
    Settled every tick as well as on each reading, because the "gone" transition
    is time-based. The first settle is recorded silently.
    """

    def __init__(
        self,
        *,
        distance_sensor: str = "distance",
        motion_sensor: str = "presence",
        row: int = 0,
        near_cm: int = 120,
        margin: int = 30,
        motion_grace: float = 8.0,
        arrive: str = "Welcome back!",
        leave: str = "See you soon",
        now: Callable[[], float] | None = None,
    ) -> None:
        self._estimator = PresenceEstimator(
            distance_sensor=distance_sensor,
            motion_sensor=motion_sensor,
            near_cm=near_cm,
            margin=margin,
            motion_grace=motion_grace,
            now=now,
        )
        self._row = row
        self._arrive = arrive
        self._leave = leave
        self._was_present: bool | None = None

    def on_sensor(self, reading: SensorReading, world: WorldState) -> list[Action]:
        if self._estimator.handles(reading.name):
            self._estimator.feed(reading)
            return self._settle()
        return []

    def on_tick(self, world: WorldState) -> list[Action]:
        return self._settle()

    def _settle(self) -> list[Action]:
        present = self._estimator.evaluate()
        if present == self._was_present:
            return []
        first = self._was_present is None
        self._was_present = present
        if first:
            return []  # prime silently on the first evaluation
        return [ShowText(self._row, self._arrive if present else self._leave)]


class ProximityGreeter(Behavior):
    """Perks up when you lean in close to Kivo (a deliberate gesture; see
    :class:`ProximityGate`). Primes silently, then speaks only on the lean-in."""

    def __init__(
        self,
        *,
        sensor: str = "distance",
        row: int = 0,
        close_below: int = 20,
        margin: int = 10,
        greeting: str = "Ooh, hello!",
    ) -> None:
        self._sensor = sensor
        self._row = row
        self._greeting = greeting
        self._gate = ProximityGate(close_below=close_below, margin=margin)
        self._was_close: bool | None = None

    def on_sensor(self, reading: SensorReading, world: WorldState) -> list[Action]:
        if reading.name != self._sensor:
            return []
        close = self._gate.update(reading.value)
        if close == self._was_close:
            return []
        first = self._was_close is None
        self._was_close = close
        if first or not close:
            return []  # prime silently; only speak on the lean-in
        return [ShowText(self._row, self._greeting)]


# The servo's neutral "looking at you" angle. Gestures swing around it: lower
# dips the head down (droop / nod-down), higher lifts it up (perk / alert).
SERVO_CENTER = 90

# Each gesture waypoint is held this many ticks (~100ms each) so the servo has
# time to actually reach it - the difference between a readable nod and a blur.
_GESTURE_HOLD = 2


@dataclass(frozen=True, slots=True)
class Mood:
    """A named feeling Kivo expresses across all three outputs: an RGB ``color``,
    a signature ``chirp`` (``(freq_hz, ms)`` notes), and a ``gesture`` (a path of
    servo angles = body language). The chirp plays a note per tick; the gesture
    holds each angle a couple of ticks so the motion reads clearly."""

    name: str
    color: tuple[int, int, int]
    chirp: tuple[tuple[int, int], ...] = ()
    gesture: tuple[int, ...] = ()


# Kivo's palette. Colours are digital RGB (7 primaries + off). Gestures are servo
# paths around SERVO_CENTER (90): a bigger swing + more waypoints reads as a real
# nod / bounce / droop rather than a twitch.
_MOODS = {
    # -- environmental / interaction moods --
    # nobody here: dark, silent, head slowly drooping down to rest.
    "away": Mood("away", (0, 0, 0), (), (75, 55, 45)),
    # lean-in: cyan, happy rising chirp, a big excited bounce.
    "excited": Mood("excited", (0, 1, 1), ((880, 80), (1320, 80)),
                    (90, 140, 90, 140, 110)),
    # night / dark: blue, low soft note, a slow gentle sway.
    "calm": Mood("calm", (0, 0, 1), ((392, 140),), (90, 100, 90)),
    # evening / dim: magenta, gentle falling chirp, relaxed settle.
    "cozy": Mood("cozy", (1, 0, 1), ((523, 90), (440, 90)), (90, 80, 85)),
    # morning: yellow, bright chirp, a happy double nod.
    "cheerful": Mood("cheerful", (1, 1, 0), ((659, 80), (880, 80)),
                     (90, 65, 95, 65, 90)),
    # afternoon + bright: white, single note, attentive lift.
    "focused": Mood("focused", (1, 1, 1), ((587, 120),), (90, 100, 95)),
    # default present: green, gentle note, a small nod.
    "content": Mood("content", (0, 1, 0), ((523, 110),), (90, 72, 92)),
    # -- webcam emotion moods (mirror how you look) --
    # happy: yellow, joyful rising chirp, a big bouncy nod.
    "happy": Mood("happy", (1, 1, 0), ((659, 80), (988, 80)),
                  (90, 135, 80, 135, 100)),
    # sad: blue, low falling chirp, a slow deep droop.
    "sad": Mood("sad", (0, 0, 1), ((440, 130), (330, 150)), (90, 70, 55, 45)),
    # surprise: white, quick high chirp, a sharp snap upward.
    "surprise": Mood("surprise", (1, 1, 1), ((1047, 60), (1319, 60)),
                     (90, 150, 145)),
    # angry: red, harsh low buzz, a sharp side-to-side jitter.
    "angry": Mood("angry", (1, 0, 0), ((196, 110), (165, 110)),
                  (90, 108, 72, 108, 72, 90)),
    # fear: magenta, wavery chirp, a shrinking tremble.
    "fear": Mood("fear", (1, 0, 1), ((587, 70), (494, 70), (587, 70)),
                 (90, 72, 62, 68, 62)),
    # disgust: green, short low note, a recoil away and back.
    "disgust": Mood("disgust", (0, 1, 0), ((262, 110),), (90, 60, 90)),
}

# Which _MOODS keys come from the webcam (a non-neutral detected expression).
_EMOTION_MOODS = frozenset(
    {"happy", "sad", "surprise", "angry", "fear", "disgust"}
)


def _mood_frames(mood: "Mood") -> list[list[Action]]:
    """Lay a mood's chirp + gesture onto per-tick frames.

    Chirp notes go one per tick. Each gesture angle is held ``_GESTURE_HOLD``
    ticks (emitted only when it changes) so the servo reaches it before the next
    move - that's what makes a nod/bounce/droop legible instead of a twitch."""
    gesture_slots: list[int | None] = []
    prev: int | None = None
    for angle in mood.gesture:
        gesture_slots.append(angle if angle != prev else None)
        gesture_slots.extend([None] * (_GESTURE_HOLD - 1))  # hold before next move
        prev = angle

    steps = max(len(mood.chirp), len(gesture_slots))
    frames: list[list[Action]] = []
    for i in range(steps):
        frame: list[Action] = []
        if i < len(mood.chirp):
            frame.append(PlayTone(*mood.chirp[i]))
        if i < len(gesture_slots) and gesture_slots[i] is not None:
            frame.append(SetServo(gesture_slots[i]))
        frames.append(frame)
    return frames


class MoodEngine(Behavior):
    """Infers Kivo's mood and expresses it with the RGB LED + buzzer.

    The mood is read from cues: the time of day, the room light, whether you're
    present, whether you lean in, and - when a webcam ``emotion`` source is wired
    - how your face looks. A detected expression is the strongest signal: Kivo
    mirrors it (happy → yellow bounce, sad → blue droop, angry → red jitter, ...).
    Seeing a face also counts as being present. Without a face it falls back to
    the environmental vibe.

    Presence is re-evaluated every tick (so leaving fades Kivo to "away"), and the
    palette shifts through the day, so the colour tracks the hour, your engagement,
    and your expression together.
    """

    def __init__(
        self,
        *,
        light_sensor: str = "light",
        motion_sensor: str = "presence",
        distance_sensor: str = "distance",
        dark_below: int = 300,
        bright_above: int = 700,
        margin: int = 40,
        near_cm: int = 120,
        near_margin: int = 30,
        motion_grace: float = 8.0,
        close_below: int = 20,
        close_margin: int = 10,
        chirps: bool = True,
        emotion: "EmotionSource | None" = None,
        now: Callable[[], datetime] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._light_sensor = light_sensor
        self._distance_sensor = distance_sensor
        self._classifier = LightClassifier(
            dark_below=dark_below, bright_above=bright_above, margin=margin
        )
        self._gate = ProximityGate(close_below=close_below, margin=close_margin)
        self._presence = PresenceEstimator(
            distance_sensor=distance_sensor,
            motion_sensor=motion_sensor,
            near_cm=near_cm,
            margin=near_margin,
            motion_grace=motion_grace,
            now=clock,
        )
        self._emotion = emotion
        self._now = now or datetime.now
        self._chirps = chirps
        self._light_label = "dim"
        self._close = False
        self._mood: str | None = None
        self._pending: list[list[Action]] = []  # remaining chirp/gesture frames

    def on_sensor(self, reading: SensorReading, world: WorldState) -> list[Action]:
        if reading.name == self._light_sensor:
            self._light_label = self._classifier.classify(reading.value)
        if reading.name == self._distance_sensor:
            self._close = self._gate.update(reading.value)
        if self._presence.handles(reading.name):
            self._presence.feed(reading)
        return self._recompute()

    def on_tick(self, world: WorldState) -> list[Action]:
        # A mood change takes priority; otherwise drip out the next chirp/gesture
        # frame (so notes don't overlap and the servo has time to move).
        changed = self._recompute()
        return changed if changed else self._next_frame()

    def _recompute(self) -> list[Action]:
        mood = self._pick()
        if mood.name == self._mood:
            return []
        self._mood = mood.name
        frames = _mood_frames(mood)
        if not self._chirps:  # chirps off -> keep gestures, drop the notes
            frames = [[a for a in f if not isinstance(a, PlayTone)] for f in frames]
        self._pending = frames[1:]
        first = frames[0] if frames else []
        return [SetColor(*mood.color), *first]

    def _next_frame(self) -> list[Action]:
        return self._pending.pop(0) if self._pending else []

    def _pick(self) -> Mood:
        emotion = self._emotion.current() if self._emotion is not None else None
        # Seeing your face is itself proof you're here, so it adds to presence.
        present = self._presence.evaluate() or emotion is not None
        if not present:
            return _MOODS["away"]
        # Your expression is the strongest signal - Kivo mirrors it.
        if emotion in _EMOTION_MOODS:
            return _MOODS[emotion]
        if self._close:
            return _MOODS["excited"]
        part = part_of_day(self._now().hour)
        if part == "night" or self._light_label == "dark":
            return _MOODS["calm"]
        if part == "evening" or self._light_label == "dim":
            return _MOODS["cozy"]
        if part == "morning":
            return _MOODS["cheerful"]
        if self._light_label == "bright":
            return _MOODS["focused"]
        return _MOODS["content"]


class FocusNudge(Behavior):
    """Notices a long, unbroken focus session and gently suggests a break.

    Focus time accumulates while you're present and resets once you take a real
    break (away for ``break_reset`` seconds); brief blips don't reset it. After
    ``focus_after`` seconds of continuous focus Kivo nudges once (a short line +
    a soft chime), then re-nudges every ``renudge_every`` seconds if you keep
    going. Time is measured on the loop clock, so no sensor needs to be chatty.
    """

    def __init__(
        self,
        *,
        distance_sensor: str = "distance",
        motion_sensor: str = "presence",
        row: int = 0,
        focus_after: float = 45 * 60,
        break_reset: float = 3 * 60,
        renudge_every: float = 20 * 60,
        near_cm: int = 120,
        near_margin: int = 30,
        motion_grace: float = 8.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._estimator = PresenceEstimator(
            distance_sensor=distance_sensor,
            motion_sensor=motion_sensor,
            near_cm=near_cm,
            margin=near_margin,
            motion_grace=motion_grace,
            now=clock,
        )
        self._row = row
        self._focus_after = focus_after
        self._break_reset = break_reset
        self._renudge_every = renudge_every
        self._clock = clock or time.monotonic
        self._focus = 0.0
        self._away = 0.0
        self._last_tick: float | None = None
        self._nudged_at: float | None = None  # focus seconds at the last nudge

    def on_sensor(self, reading: SensorReading, world: WorldState) -> list[Action]:
        if self._estimator.handles(reading.name):
            self._estimator.feed(reading)
        return []  # timing decisions happen on the tick

    def on_tick(self, world: WorldState) -> list[Action]:
        now = self._clock()
        if self._last_tick is None:
            self._last_tick = now
            return []
        dt = now - self._last_tick
        self._last_tick = now

        if self._estimator.evaluate():
            self._focus += dt
            self._away = 0.0
        else:
            self._away += dt
            if self._away >= self._break_reset:  # a real break: start fresh
                self._focus = 0.0
                self._nudged_at = None
            return []

        if self._focus >= self._focus_after and (
            self._nudged_at is None
            or self._focus - self._nudged_at >= self._renudge_every
        ):
            self._nudged_at = self._focus
            mins = int(self._focus // 60)
            return [
                ShowText(self._row, f"Break? {mins} min focus"),
                PlayTone(784, 160),
            ]
        return []


class PomodoroTimer(Behavior):
    """A simple pomodoro: alternating focus / break intervals shown on a row,
    with a chime at each switch. Updates the display only when the shown minute
    changes, so it barely touches the link."""

    def __init__(
        self,
        *,
        row: int = 1,
        focus_min: int = 25,
        break_min: int = 5,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._row = row
        self._focus = focus_min * 60
        self._break = break_min * 60
        self._clock = clock or time.monotonic
        self._start: float | None = None
        self._on_break = False
        self._shown: str | None = None

    def on_start(self, world: WorldState) -> list[Action]:
        self._start = self._clock()
        return self._render()

    def on_tick(self, world: WorldState) -> list[Action]:
        return self._render()

    def _render(self) -> list[Action]:
        if self._start is None:
            self._start = self._clock()
        actions: list[Action] = []
        duration = self._break if self._on_break else self._focus
        elapsed = self._clock() - self._start
        if elapsed >= duration:  # switch phase
            self._on_break = not self._on_break
            self._start = self._clock()
            elapsed = 0.0
            duration = self._break if self._on_break else self._focus
            actions.append(PlayTone(880 if self._on_break else 659, 180))
        remaining = max(0.0, duration - elapsed)
        mins = int(remaining // 60) + (1 if remaining % 60 else 0)
        text = f"{'Break' if self._on_break else 'Focus'} {mins:>2}m"
        if text != self._shown:
            self._shown = text
            actions.append(ShowText(self._row, text))
        return actions


# Self-contained reactions to a button press, expressed like moods (colour +
# chirp + gesture) and sequenced by the same per-tick frames.
_PET = Mood("pet", (1, 0, 1), ((880, 80), (1175, 80)), (90, 130, 95))
_DANCE = Mood(
    "dance", (0, 1, 1),
    ((659, 70), (880, 70), (1047, 70), (880, 70)),
    (60, 120, 60, 120, 90),
)
_ACK = Mood("ack", (0, 0, 0), (), (SERVO_CENTER,))  # calm down / dismiss


class ButtonEvent(Behavior):
    """Turns the raw button stream into intentional interactions.

    The firmware streams ``button 1``/``button 0`` on debounced press/release;
    this reads the timing into gestures and reacts, self-contained (colour +
    chirp + servo), so a press never depends on any other behaviour:

    * **tap** -> pet Kivo (a happy magenta bounce)
    * **double-tap** -> a playful cyan dance
    * **hold** -> shush / dismiss (calm down, centre, clear the line)

    A single tap is only confirmed once the double-tap window passes with no
    second tap, so a double-tap never also fires a tap.
    """

    def __init__(
        self,
        *,
        sensor: str = "button",
        row: int = 0,
        long_press: float = 0.7,
        double_window: float = 0.35,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._sensor = sensor
        self._row = row
        self._long_press = long_press
        self._double_window = double_window
        self._clock = clock or time.monotonic
        self._press_at: float | None = None
        self._tap_at: float | None = None
        self._pending: list[list[Action]] = []

    def on_sensor(self, reading: SensorReading, world: WorldState) -> list[Action]:
        if reading.name != self._sensor:
            return []
        now = self._clock()
        if reading.value >= 1:  # pressed
            self._press_at = now
            return []
        # released
        press_at, self._press_at = self._press_at, None
        if press_at is None:
            return []
        if now - press_at >= self._long_press:  # a hold
            self._tap_at = None
            return self._react(_ACK, "resting")
        if self._tap_at is not None and now - self._tap_at <= self._double_window:
            self._tap_at = None  # second tap in time -> double
            return self._react(_DANCE, "wheee!")
        self._tap_at = now  # first tap; wait for a possible second
        return []

    def on_tick(self, world: WorldState) -> list[Action]:
        if (
            self._tap_at is not None
            and self._clock() - self._tap_at > self._double_window
        ):
            self._tap_at = None  # no second tap came -> it was a single tap
            return self._react(_PET, "hehe :)")
        return self._pending.pop(0) if self._pending else []

    def _react(self, mood: Mood, text: str) -> list[Action]:
        frames = _mood_frames(mood)
        self._pending = frames[1:]
        first = frames[0] if frames else []
        return [SetColor(*mood.color), ShowText(self._row, text), *first]


# -- the Brain loop ----------------------------------------------------------

# How long each loop iteration waits for events. Short enough that Ctrl+C stays
# responsive (the blocking read returns at least this often).
_DEFAULT_POLL_INTERVAL = 0.1

# The LCD is 16 columns wide (mirrors ``KIVO_LCD_COLS`` in firmware/src/config.h;
# the device exposes no geometry query). The device writes text in place and does
# NOT blank the rest of the row, so RowScroller pads/scrolls every line to the
# full width - a shorter line then wipes any leftover characters.
_LCD_COLS = 16


class Brain:
    def __init__(
        self,
        client: DeviceClient,
        behaviors: Iterable[Behavior],
        *,
        sensors: Sequence[str] = (),
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
    ) -> None:
        self._client = client
        self._behaviors = list(behaviors)
        self._sensors = list(sensors)
        self._poll_interval = poll_interval
        self._world = WorldState()
        self._events: deque[Event] = deque()
        # One marquee per row: long lines scroll instead of being truncated.
        self._scrollers: dict[int, RowScroller] = {}
        # Action types the device rejected as unknown (e.g. old firmware or a
        # peripheral not built) - skipped from then on so one missing capability
        # doesn't take down the whole companion.
        self._unsupported: set[type] = set()

    @property
    def world(self) -> WorldState:
        return self._world

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        """Subscribe to sensors and run each behaviour's start hook."""
        # Route every device event into our queue; we process it on our own loop
        # rather than inside this callback (no re-entrancy mid-command).
        self._client.set_event_handler(self._events.append)
        self._client.display_clear()
        for name in self._sensors:
            self._client.subscribe_sensor(name)
        for behavior in self._behaviors:
            self._apply(behavior.on_start(self._world))
        # Subscribing prompts an initial reading; handle anything already queued.
        self._drain()

    def step(self) -> None:
        """One iteration: wait briefly for events, react to all of them, let
        behaviours emit work that finished on their own schedule, then advance
        the scrolling animation of any line too long to fit."""
        self._client.pump_events(self._poll_interval)
        self._drain()
        self._poll()
        self._animate()

    def run(self) -> None:
        """Run forever. Stop by raising ``KeyboardInterrupt`` in the caller."""
        self.start()
        while True:
            self.step()

    # -- internals ------------------------------------------------------------

    def _drain(self) -> None:
        while self._events:
            self._react(self._events.popleft())

    def _poll(self) -> None:
        """Let each behaviour emit actions that became ready between events (e.g.
        an async AI line). On the Brain's own loop, preserving ADR-0004."""
        for behavior in self._behaviors:
            self._apply(behavior.on_tick(self._world))

    def _animate(self) -> None:
        """Advance each row's marquee by one frame, writing only when the visible
        window actually changed (a short, static line writes nothing here)."""
        for row, scroller in self._scrollers.items():
            window = scroller.tick()
            if window is not None:
                self._client.display_write(window, row=row)

    def _react(self, event: Event) -> None:
        reading = DeviceClient.parse_sensor_event(event)
        if reading is not None:
            self._world.update_sensor(reading)
            for behavior in self._behaviors:
                self._apply(behavior.on_sensor(reading, self._world))
        else:
            _log.debug("unhandled event: %s %s", event.name, event.data)

    def _apply(self, actions: list[Action]) -> None:
        for action in actions:
            self._execute(action)

    def _execute(self, action: Action) -> None:
        if type(action) in self._unsupported:
            return
        try:
            self._perform(action)
        except DeviceError as exc:
            if exc.code == ErrorCode.UNKNOWN_OP:
                # The firmware doesn't know this op - disable it and carry on so
                # the rest of Kivo keeps working (reflash to enable it).
                self._unsupported.add(type(action))
                _log.warning(
                    "device rejected %s (unknown op) - skipping it; reflash the "
                    "firmware to enable this capability",
                    type(action).__name__,
                )
            else:
                raise

    def _perform(self, action: Action) -> None:
        if isinstance(action, ShowText):
            _log.info("show row %d: %r", action.row, action.text)
            # Hand the whole line to the row's marquee: it shows what fits now and
            # scrolls the rest over the next ticks, so no word is ever dropped.
            scroller = self._scrollers.get(action.row)
            if scroller is None:
                scroller = RowScroller(_LCD_COLS)
                self._scrollers[action.row] = scroller
            window = scroller.set(action.text)
            self._client.display_write(window, row=action.row)
        elif isinstance(action, ClearScreen):
            _log.info("clear display")
            self._scrollers.clear()
            self._client.display_clear()
        elif isinstance(action, SetColor):
            _log.info("led %d%d%d", action.r, action.g, action.b)
            self._client.led_set(action.r, action.g, action.b)
        elif isinstance(action, PlayTone):
            _log.info("tone %dHz %dms", action.freq, action.ms)
            self._client.tone_play(action.freq, action.ms)
        elif isinstance(action, SetServo):
            _log.info("servo %d", action.angle)
            self._client.servo_set(action.angle)
        else:  # pragma: no cover - guards against an unhandled Action variant
            _log.warning("unknown action: %r", action)


# -- default personality -----------------------------------------------------

# The default senses Kivo subscribes to. A behaviour reacts only to sensors that
# are actually subscribed, so these are kept in step with default_behaviors().
DEFAULT_SENSORS = ("light", "presence", "distance")


def default_behaviors() -> list[Behavior]:
    """Kivo's starter personality: greet by time of day, welcome arrivals, perk
    up on a lean-in, narrate the room's light, and express its mood in colour."""
    return [
        TimeGreeter(),
        PresenceGreeter(),
        ProximityGreeter(),
        LightMood(sensor="light"),
        MoodEngine(),
    ]
