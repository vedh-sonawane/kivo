"""Tests for Kivo's long-term memory and continuity-aware greeting."""

from datetime import datetime

from kivo.ai import AiNarrator, FakeAiClient
from kivo.brain import ShowText, WorldState
from kivo.device import SensorReading
from kivo.memory import Memory, MemoryGreeter, ai_context, visit_line, wake_line


def _at(y, m, d, h):
    return lambda: datetime(y, m, d, h, 0)


# -- the store ---------------------------------------------------------------


def test_first_session_ever_is_recognised(tmp_path):
    mem = Memory(tmp_path / "m.json", now=_at(2026, 8, 2, 9))
    cont = mem.note_session()
    assert cont.first_ever is True
    assert wake_line(cont) == "Hi! I'm Kivo"


def test_returning_after_days_reports_the_gap(tmp_path):
    path = tmp_path / "m.json"
    Memory(path, now=_at(2026, 8, 1, 9)).note_session()
    cont = Memory(path, now=_at(2026, 8, 3, 9)).note_session()
    assert cont.first_ever is False
    assert cont.days_since == 2
    assert wake_line(cont) == "Welcome back! 2 days"


def test_visits_are_counted_per_day(tmp_path):
    mem = Memory(tmp_path / "m.json", now=_at(2026, 8, 2, 14))
    assert mem.note_visit().visits_today == 1
    mem.note_visit()
    third = mem.note_visit()
    assert third.visits_today == 3
    assert visit_line(third) == "Back again! (3x today)"


def test_usual_arrival_hour_is_learned(tmp_path):
    path = tmp_path / "m.json"
    for day in (1, 2, 3):  # arrive at 9am three days running
        Memory(path, now=_at(2026, 8, day, 9)).note_visit()
    # A same-day wake at the usual 9am hour -> "right on time" (no days-away gap).
    cont = Memory(path, now=_at(2026, 8, 3, 9)).note_session()
    assert cont.usual_hour is True
    assert cont.days_since == 0
    assert wake_line(cont) == "Good morning, right on time"


def test_memory_persists_across_instances(tmp_path):
    path = tmp_path / "m.json"
    Memory(path, now=_at(2026, 8, 1, 9)).note_session()
    cont = Memory(path, now=_at(2026, 8, 1, 10)).note_session()
    assert cont.total_sessions == 1  # it remembered the first run


def test_ai_context_describes_the_history(tmp_path):
    path = tmp_path / "m.json"
    Memory(path, now=_at(2026, 8, 1, 9)).note_session()
    cont = Memory(path, now=_at(2026, 8, 2, 9)).note_session()
    text = ai_context(cont)
    assert "yesterday" in text
    assert "sessions together" in text


# -- deterministic greeter ---------------------------------------------------


def test_memory_greeter_greets_first_timer(tmp_path):
    mem = Memory(tmp_path / "m.json", now=_at(2026, 8, 2, 9))
    assert MemoryGreeter(mem).on_start(WorldState()) == [ShowText(0, "Hi! I'm Kivo")]


def test_memory_greeter_counts_visits_on_arrival(tmp_path):
    mem = Memory(tmp_path / "m.json", now=_at(2026, 8, 2, 14))
    greeter = MemoryGreeter(mem, near_cm=120)
    world = WorldState()
    greeter.on_start(world)  # records the session
    assert greeter.on_sensor(SensorReading("distance", 300), world) == []  # prime far
    assert greeter.on_sensor(SensorReading("distance", 50), world) == [
        ShowText(0, "Welcome back!")
    ]


# -- AI voice weaving in memory ----------------------------------------------


def test_ai_greeting_is_given_the_memory_context(tmp_path):
    seen = {}

    def responder(prompt, system):
        seen["prompt"] = prompt
        return "hey"

    mem = Memory(tmp_path / "m.json", now=_at(2026, 8, 2, 9))
    narrator = AiNarrator(
        FakeAiClient(responder), memory=mem, background=False, now=_at(2026, 8, 2, 9)
    )
    narrator.on_start(WorldState())
    assert "first time" in seen["prompt"]  # the AI is told this is a first meeting
