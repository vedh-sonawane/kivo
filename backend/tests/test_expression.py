"""Tests for Kivo's expressions: the RGB LED / buzzer capabilities and the
MoodEngine that drives them from the inferred mood."""

from datetime import datetime

from kivo.brain import Brain, MoodEngine, PlayTone, SetColor, WorldState
from kivo.device import DeviceClient, SensorReading
from kivo.transport import FakeTransport


# -- device capabilities against the emulator --------------------------------


def test_led_set_and_tone_play_reach_the_device():
    transport = FakeTransport()
    with DeviceClient(transport) as client:
        client.led_set(1, 0, 1)
        client.tone_play(880, 100)
    assert transport.led == (1, 0, 1)
    assert (880, 100) in transport.tones


# -- MoodEngine (pure) -------------------------------------------------------


def _engine(hour=10, **kw):
    return MoodEngine(now=lambda: datetime(2026, 7, 30, hour, 0), **kw)


def test_mood_is_away_and_dark_when_nobody_is_present():
    engine = _engine()
    # No distance reading -> not present -> LED off, no chirp.
    assert engine.on_tick(WorldState()) == [SetColor(0, 0, 0)]


def test_mood_is_cheerful_yellow_on_a_bright_morning():
    engine = _engine(hour=8, bright_above=700)
    world = WorldState()
    engine.on_sensor(SensorReading("light", 900), world)  # bright
    actions = engine.on_sensor(SensorReading("distance", 60), world)  # present
    assert SetColor(1, 1, 0) in actions  # cheerful = yellow
    assert any(isinstance(a, PlayTone) for a in actions)  # and a chirp


def test_leaning_in_makes_kivo_excited_cyan_with_a_two_note_chirp():
    engine = _engine(hour=14)
    world = WorldState()
    change = engine.on_sensor(SensorReading("distance", 10), world)  # near + close
    assert SetColor(0, 1, 1) in change  # excited = cyan
    assert PlayTone(880, 80) in change  # first note now
    # The second note plays on the next tick (so notes never overlap)...
    assert engine.on_tick(world) == [PlayTone(1320, 80)]
    # ...then the chirp is done.
    assert engine.on_tick(world) == []


def test_mood_only_changes_the_led_when_the_mood_changes():
    engine = _engine(hour=14)
    world = WorldState()
    engine.on_sensor(SensorReading("distance", 60), world)  # settle into a mood
    for _ in range(5):
        engine.on_tick(world)  # drain any chirp
    # A small wobble that doesn't change the mood emits nothing.
    assert engine.on_sensor(SensorReading("distance", 62), world) == []


# -- end to end through the Brain --------------------------------------------


def test_brain_lights_the_mood_led_when_you_arrive():
    transport = FakeTransport()
    with DeviceClient(transport) as client:
        brain = Brain(
            client,
            [MoodEngine(now=lambda: datetime(2026, 7, 30, 8, 0))],
            sensors=["light", "presence", "distance"],
            poll_interval=0,
        )
        brain.start()
        assert transport.led == (0, 0, 0)  # nobody here yet -> dark
        transport.set_sensor("light", 900)  # bright
        transport.set_sensor("distance", 50)  # come near -> present
        brain.step()
    assert transport.led == (1, 1, 0)  # bright morning + present -> cheerful yellow
