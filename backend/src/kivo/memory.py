"""Kivo's long-term memory - continuity across sessions.

Everything else about Kivo is in-the-moment; this is what lets it *remember* you.
A tiny JSON store (like calibration) records when it has seen you: total sessions,
visits per day, the hours you usually show up, and when it last saw you. From that
it derives a :class:`Continuity` - "first time ever", "back after 2 days", "3rd
visit today", "right on your usual schedule" - which both a deterministic greeter
and the AI voice use to greet you like something that knows you.

File: ``$KIVO_MEMORY_PATH`` if set, else ``~/.kivo/memory.json``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .brain import Behavior, PresenceEstimator, ShowText, part_of_day

# Keep only recent per-day visit counts so the file can't grow without bound.
_KEEP_DAYS = 45
# You've "usually" arrived at an hour once Kivo has seen it happen this often.
_USUAL_HOUR_MIN = 3

_GREETINGS = {
    "morning": "Good morning",
    "afternoon": "Good afternoon",
    "evening": "Good evening",
    "night": "Hi, night owl",
}


def memory_path() -> Path:
    override = os.environ.get("KIVO_MEMORY_PATH")
    return Path(override) if override else Path.home() / ".kivo" / "memory.json"


@dataclass(frozen=True, slots=True)
class Continuity:
    """What Kivo remembers about you at this moment of greeting."""

    first_ever: bool
    days_since: int | None  # days since last seen; None if first ever
    visits_today: int
    total_sessions: int
    total_visits: int
    usual_hour: bool
    hour: int


class Memory:
    """The persistent store. Records sessions/visits and derives continuity."""

    def __init__(self, path: Path | None = None, *, now=None) -> None:
        self._path = path or memory_path()
        self._now = now or datetime.now
        self._data = self._load()

    # -- recording ------------------------------------------------------------

    def note_session(self) -> Continuity:
        """Record that Kivo just woke (one ``kivo run``); return prior continuity."""
        now = self._now()
        cont = self._continuity(now)  # computed against the *previous* state
        self._data["total_sessions"] = self._data.get("total_sessions", 0) + 1
        self._data.setdefault("first_seen", now.isoformat())
        self._data["last_seen"] = now.isoformat()
        self._save()
        return cont

    def note_visit(self) -> Continuity:
        """Record that you just arrived at the desk; return continuity incl. this visit."""
        now = self._now()
        today = now.date().isoformat()
        visits = self._data.setdefault("visits_by_date", {})
        visits[today] = visits.get(today, 0) + 1
        self._prune(visits, now)
        hours = self._data.setdefault("arrival_hours", {})
        hours[str(now.hour)] = hours.get(str(now.hour), 0) + 1
        self._data["total_visits"] = self._data.get("total_visits", 0) + 1
        self._data.setdefault("first_seen", now.isoformat())
        cont = self._continuity(now)  # after counting this visit
        self._data["last_seen"] = now.isoformat()
        self._save()
        return cont

    # -- AI context strings (so callers don't need the phrasing helpers) ------

    def session_context(self) -> str:
        return ai_context(self.note_session())

    def visit_context(self) -> str:
        return ai_context(self.note_visit())

    # -- internals ------------------------------------------------------------

    def _continuity(self, now: datetime) -> Continuity:
        d = self._data
        first_ever = "last_seen" not in d
        days_since: int | None = None
        last = d.get("last_seen")
        if last:
            try:
                days_since = (now.date() - datetime.fromisoformat(last).date()).days
            except ValueError:
                days_since = None
        today = now.date().isoformat()
        hours = d.get("arrival_hours", {})
        return Continuity(
            first_ever=first_ever,
            days_since=days_since,
            visits_today=d.get("visits_by_date", {}).get(today, 0),
            total_sessions=d.get("total_sessions", 0),
            total_visits=d.get("total_visits", 0),
            usual_hour=hours.get(str(now.hour), 0) >= _USUAL_HOUR_MIN,
            hour=now.hour,
        )

    @staticmethod
    def _prune(visits: dict, now: datetime) -> None:
        cutoff = now.date() - timedelta(days=_KEEP_DAYS)
        for key in list(visits):
            try:
                if date.fromisoformat(key) < cutoff:
                    del visits[key]
            except ValueError:
                del visits[key]

    def _load(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, indent=2), encoding="utf-8"
            )
        except OSError:
            pass  # memory is a nicety; never let a write failure break the run


# -- phrasing ----------------------------------------------------------------


def wake_line(cont: Continuity) -> str:
    """A short, continuity-aware wake greeting for the LCD (it scrolls if long)."""
    greeting = _GREETINGS[part_of_day(cont.hour)]
    if cont.first_ever:
        return "Hi! I'm Kivo"
    if cont.days_since is not None and cont.days_since >= 7:
        return "Long time no see!"
    if cont.days_since is not None and cont.days_since >= 1:
        unit = "day" if cont.days_since == 1 else "days"
        return f"Welcome back! {cont.days_since} {unit}"
    if cont.usual_hour:
        return f"{greeting}, right on time"
    return greeting


def visit_line(cont: Continuity) -> str:
    """A short greeting for arriving mid-session, aware of how often you've come."""
    if cont.visits_today >= 3:
        return f"Back again! ({cont.visits_today}x today)"
    if cont.visits_today == 2:
        return "You're back!"
    return "Welcome back!"


def ai_context(cont: Continuity) -> str:
    """A phrase describing the history, for the AI to weave into a greeting."""
    if cont.first_ever:
        return "this is the very first time you've ever met them"
    bits: list[str] = []
    if cont.days_since == 0:
        bits.append("you last saw them earlier today")
    elif cont.days_since == 1:
        bits.append("you last saw them yesterday")
    elif cont.days_since is not None and cont.days_since > 1:
        bits.append(f"you last saw them {cont.days_since} days ago")
    if cont.visits_today >= 2:
        bits.append(f"this is their visit number {cont.visits_today} today")
    if cont.usual_hour:
        bits.append("they usually come by around this time of day")
    if cont.total_sessions >= 1:
        bits.append(f"you've shared {cont.total_sessions} sessions together")
    return "; ".join(bits)


# -- deterministic memory-aware greeter (non-AI mode) ------------------------


class MemoryGreeter(Behavior):
    """Greets with continuity: a history-aware line on wake, a visit-count line on
    arrival, and a farewell on leaving. Records the session/visit as it goes.

    Reuses the fused presence estimate (see :class:`PresenceEstimator`) so
    "arrival" and "left" mean the same thing they do everywhere else in Kivo.
    """

    def __init__(
        self,
        memory: Memory,
        *,
        row: int = 0,
        distance_sensor: str = "distance",
        motion_sensor: str = "presence",
        near_cm: int = 120,
        near_margin: int = 30,
        motion_grace: float = 8.0,
        farewell: str = "See you soon",
        clock=None,
    ) -> None:
        self._memory = memory
        self._row = row
        self._farewell = farewell
        self._estimator = PresenceEstimator(
            distance_sensor=distance_sensor,
            motion_sensor=motion_sensor,
            near_cm=near_cm,
            margin=near_margin,
            motion_grace=motion_grace,
            now=clock,
        )
        self._was_present: bool | None = None

    def on_start(self, world) -> list:
        return [ShowText(self._row, wake_line(self._memory.note_session()))]

    def on_sensor(self, reading, world) -> list:
        if self._estimator.handles(reading.name):
            self._estimator.feed(reading)
            return self._settle()
        return []

    def on_tick(self, world) -> list:
        return self._settle()

    def _settle(self) -> list:
        present = self._estimator.evaluate()
        if present == self._was_present:
            return []
        first = self._was_present is None
        self._was_present = present
        if first:
            return []  # prime silently
        if present:
            return [ShowText(self._row, visit_line(self._memory.note_visit()))]
        return [ShowText(self._row, self._farewell)]
