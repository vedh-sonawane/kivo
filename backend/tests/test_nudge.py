"""Tests for the useful nudges: the focus/break reminder and the pomodoro timer."""

from kivo.brain import FocusNudge, PlayTone, PomodoroTimer, ShowText, WorldState
from kivo.device import SensorReading


def _present(nudge, world):
    nudge.on_sensor(SensorReading("distance", 50), world)  # near -> present


def _away(nudge, world):
    nudge.on_sensor(SensorReading("distance", 300), world)  # far -> away


# -- FocusNudge --------------------------------------------------------------


def test_no_nudge_before_the_focus_threshold():
    clock = [0.0]
    nudge = FocusNudge(focus_after=60, break_reset=30, clock=lambda: clock[0])
    world = WorldState()
    _present(nudge, world)
    assert nudge.on_tick(world) == []  # baseline tick
    clock[0] = 40  # 40s of focus, under the 60s threshold
    assert nudge.on_tick(world) == []


def test_nudge_after_sustained_focus():
    clock = [0.0]
    nudge = FocusNudge(focus_after=60, break_reset=30, clock=lambda: clock[0])
    world = WorldState()
    _present(nudge, world)
    nudge.on_tick(world)  # baseline
    clock[0] = 70  # 70s of continuous focus
    actions = nudge.on_tick(world)
    assert any(isinstance(a, ShowText) for a in actions)
    assert any(isinstance(a, PlayTone) for a in actions)
    # It doesn't nag every tick.
    clock[0] = 75
    assert nudge.on_tick(world) == []


def test_a_real_break_resets_the_focus_timer():
    clock = [0.0]
    nudge = FocusNudge(focus_after=60, break_reset=30, clock=lambda: clock[0])
    world = WorldState()
    _present(nudge, world)
    nudge.on_tick(world)  # baseline
    clock[0] = 70
    assert nudge.on_tick(world)  # nudged once

    _away(nudge, world)  # step away...
    clock[0] = 105  # ...for 35s (> 30s break_reset) -> counts as a break
    assert nudge.on_tick(world) == []

    _present(nudge, world)  # back at it, focus starts from zero
    clock[0] = 145  # only 40s of new focus
    assert nudge.on_tick(world) == []  # not nudged again yet


# -- PomodoroTimer -----------------------------------------------------------


def test_pomodoro_shows_focus_then_switches_to_break_with_a_chime():
    clock = [0.0]
    pomo = PomodoroTimer(focus_min=1, break_min=1, clock=lambda: clock[0])  # 60s each
    world = WorldState()
    start = pomo.on_start(world)
    assert any(isinstance(a, ShowText) and "Focus" in a.text for a in start)

    clock[0] = 30  # mid-focus, same displayed minute -> no redundant write
    assert pomo.on_tick(world) == []

    clock[0] = 65  # focus interval elapsed -> switch to break
    actions = pomo.on_tick(world)
    assert any(isinstance(a, ShowText) and "Break" in a.text for a in actions)
    assert any(isinstance(a, PlayTone) for a in actions)
