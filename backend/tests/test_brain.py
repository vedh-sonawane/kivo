"""Tests for the Brain: pure behaviours, and an end-to-end autonomous loop."""

from datetime import datetime

from kivo.brain import (
    Brain,
    Greeter,
    LightClassifier,
    LightMood,
    PresenceGreeter,
    ProximityGate,
    ProximityGreeter,
    ShowText,
    TimeGreeter,
    WorldState,
    part_of_day,
)
from kivo.device import DeviceClient, SensorReading
from kivo.transport import FakeTransport


# -- pure behaviour tests (no device) ----------------------------------------


def test_greeter_greets_on_start():
    actions = Greeter("Hello").on_start(WorldState())
    assert actions == [ShowText(0, "Hello")]


def test_part_of_day_buckets():
    assert part_of_day(8) == "morning"
    assert part_of_day(14) == "afternoon"
    assert part_of_day(19) == "evening"
    assert part_of_day(2) == "night"


def test_time_greeter_greets_by_hour():
    fixed_evening = lambda: datetime(2026, 7, 30, 19, 0)  # noqa: E731
    assert TimeGreeter(now=fixed_evening).on_start(WorldState()) == [
        ShowText(0, "Good evening")
    ]


def test_light_classifier_hysteresis_ignores_boundary_jitter():
    c = LightClassifier(dark_below=300, bright_above=700, margin=40)
    assert c.classify(290) == "dark"  # first reading, plain threshold
    assert c.classify(310) == "dark"  # within margin of 300 -> no flap
    assert c.classify(345) == "dim"  # clearly past 300+40 -> switch
    assert c.classify(305) == "dim"  # within margin -> no flap back


def test_light_classifier_allows_large_jumps():
    c = LightClassifier(dark_below=300, bright_above=700, margin=40)
    assert c.classify(950) == "bright"
    assert c.classify(40) == "dark"  # bright -> dark directly, not stuck at dim


def test_light_mood_classifies_and_pads_labels():
    mood = LightMood(dark_below=300, bright_above=700)
    world = WorldState()
    # bright
    assert mood.on_sensor(SensorReading("light", 900), world) == [
        ShowText(1, "Room: bright")
    ]
    # dim (padded to the width of the longest label so no stale chars remain)
    assert mood.on_sensor(SensorReading("light", 500), world) == [
        ShowText(1, "Room: dim   ")
    ]


def test_light_mood_only_speaks_on_change():
    mood = LightMood(dark_below=300, bright_above=700)
    world = WorldState()
    first = mood.on_sensor(SensorReading("light", 100), world)
    again = mood.on_sensor(SensorReading("light", 120), world)  # still "dark"
    assert first == [ShowText(1, "Room: dark  ")]
    assert again == []  # unchanged mood => silence


def test_light_mood_ignores_other_sensors():
    assert LightMood(sensor="light").on_sensor(SensorReading("temp", 900), WorldState()) == []


def _greeter(clock, **kw):
    return PresenceGreeter(
        near_cm=120, margin=30, motion_grace=8.0,
        arrive="Hi!", leave="Bye", now=lambda: clock[0], **kw,
    )


def test_presence_welcomes_on_approach_and_byes_only_when_far():
    clock = [0.0]
    greeter = _greeter(clock)
    world = WorldState()
    assert greeter.on_sensor(SensorReading("distance", 300), world) == []  # prime far
    assert greeter.on_sensor(SensorReading("distance", 50), world) == [
        ShowText(0, "Hi!")
    ]  # came near
    assert greeter.on_sensor(SensorReading("distance", 300), world) == [
        ShowText(0, "Bye")
    ]  # moved away


def test_presence_never_byes_a_still_person_who_is_near():
    # The core fix: sitting still up close sends no new readings, yet the
    # per-tick re-evaluation must keep Kivo quiet (never a false goodbye).
    clock = [0.0]
    greeter = _greeter(clock)
    world = WorldState()
    greeter.on_sensor(SensorReading("distance", 40), world)  # prime near (present)
    for _ in range(50):
        clock[0] += 1.0  # time passes with no readings at all
        assert greeter.on_tick(world) == []  # still here -> silence


def test_presence_motion_grace_delays_bye_until_you_stop_moving():
    clock = [100.0]
    greeter = _greeter(clock)
    world = WorldState()
    greeter.on_sensor(SensorReading("distance", 40), world)  # prime near
    greeter.on_sensor(SensorReading("presence", 1), world)  # motion seen now
    # Move far, but motion was just seen -> still "here" (no premature bye).
    assert greeter.on_sensor(SensorReading("distance", 300), world) == []
    clock[0] += 4.0
    assert greeter.on_tick(world) == []  # within grace
    clock[0] += 6.0  # now past the 8s grace with no further motion
    assert greeter.on_tick(world) == [ShowText(0, "Bye")]


def test_presence_greeter_ignores_other_sensors():
    assert PresenceGreeter().on_sensor(SensorReading("light", 900), WorldState()) == []


def test_proximity_gate_hysteresis():
    gate = ProximityGate(close_below=20, margin=10)
    assert gate.update(50) is False  # far
    assert gate.update(15) is True  # crossed in -> close
    assert gate.update(25) is True  # within margin (20+10) -> still close
    assert gate.update(35) is False  # past 30 -> no longer close


def test_proximity_greeter_speaks_only_on_lean_in():
    greeter = ProximityGreeter(close_below=20, margin=10, greeting="Ooh, hi!")
    world = WorldState()
    assert greeter.on_sensor(SensorReading("distance", 100), world) == []  # prime far
    assert greeter.on_sensor(SensorReading("distance", 10), world) == [
        ShowText(0, "Ooh, hi!")
    ]  # lean in
    assert greeter.on_sensor(SensorReading("distance", 12), world) == []  # still close
    assert greeter.on_sensor(SensorReading("distance", 100), world) == []  # pull back: quiet


def test_proximity_greeter_primed_close_does_not_fire():
    # Starting Kivo while already leaning in must not fire on the first reading.
    greeter = ProximityGreeter(close_below=20)
    assert greeter.on_sensor(SensorReading("distance", 5), WorldState()) == []


def test_proximity_greeter_ignores_other_sensors():
    assert ProximityGreeter().on_sensor(SensorReading("light", 900), WorldState()) == []


# -- end-to-end: Brain driving the emulated device ---------------------------


def test_brain_greets_and_reflects_light_on_the_screen():
    transport = FakeTransport()  # initial light = 512 (dim)
    with DeviceClient(transport) as client:
        # Explicit behaviours keep this deterministic (default greeting is
        # time-of-day dependent).
        brain = Brain(client, [Greeter(), LightMood()], sensors=["light"])
        brain.start()  # subscribes -> initial reading -> reacts

        assert transport.screen[0].startswith("Hi, I'm Kivo")
        assert "dim" in transport.screen[1]

        # The room brightens: the device streams it, the Brain reacts.
        transport.set_sensor("light", 950)
        brain.step()
        assert "bright" in transport.screen[1]

        # And darkens all the way.
        transport.set_sensor("light", 50)
        brain.step()
        assert "dark" in transport.screen[1]


def test_brain_scrolls_a_line_too_long_for_the_screen():
    transport = FakeTransport()
    # poll_interval=0 keeps the loop from sleeping so the test runs instantly.
    with DeviceClient(transport) as client:
        brain = Brain(
            client, [Greeter("Kivo says hello there friend")], poll_interval=0
        )
        brain.start()
        assert transport.screen[0].startswith("Kivo says hello")  # not truncated

        windows = {transport.screen[0]}
        for _ in range(150):
            brain.step()
            windows.add(transport.screen[0])

    assert len(windows) > 1  # it actually animated
    assert any("friend" in w for w in windows)  # the dropped tail now shows


def test_brain_updates_world_state():
    transport = FakeTransport()
    with DeviceClient(transport) as client:
        brain = Brain(client, [], sensors=["light"])
        brain.start()
        transport.set_sensor("light", 777)
        brain.step()
    assert brain.world.sensor("light") == 777
