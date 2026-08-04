"""Tests for Kivo's expressions: the RGB LED / buzzer capabilities and the
MoodEngine that drives them from the inferred mood."""

from datetime import datetime

from kivo.brain import Brain, MoodEngine, PlayTone, SetColor, SetServo, WorldState
from kivo.device import DeviceClient, SensorReading
from kivo.protocol import ErrorCode
from kivo.transport import FakeTransport


# -- device capabilities against the emulator --------------------------------


def test_led_tone_and_servo_reach_the_device():
    transport = FakeTransport()
    with DeviceClient(transport) as client:
        client.led_set(1, 0, 1)
        client.tone_play(880, 100)
        client.servo_set(120)
    assert transport.led == (1, 0, 1)
    assert (880, 100) in transport.tones
    assert transport.servo == 120
    assert transport.servo_moves == [120]


# -- MoodEngine (pure) -------------------------------------------------------


def _engine(hour=10, **kw):
    return MoodEngine(now=lambda: datetime(2026, 7, 30, hour, 0), **kw)


def test_mood_is_away_and_dark_when_nobody_is_present():
    engine = _engine()
    # No distance reading -> not present -> LED off and silent (no chirp).
    actions = engine.on_tick(WorldState())
    assert SetColor(0, 0, 0) in actions
    assert not any(isinstance(a, PlayTone) for a in actions)


def test_mood_is_cheerful_yellow_on_a_bright_morning():
    engine = _engine(hour=8, bright_above=700)
    world = WorldState()
    engine.on_sensor(SensorReading("light", 900), world)  # bright
    actions = engine.on_sensor(SensorReading("distance", 60), world)  # present
    assert SetColor(1, 1, 0) in actions  # cheerful = yellow
    assert any(isinstance(a, PlayTone) for a in actions)  # and a chirp


def _servo_path(engine, world, ticks=14):
    """Collect the servo angles a just-started gesture emits over `ticks`."""
    angles = []
    for _ in range(ticks):
        angles += [a.angle for a in engine.on_tick(world) if isinstance(a, SetServo)]
    return angles


def test_leaning_in_makes_kivo_excited_cyan_and_bounces_the_servo():
    engine = _engine(hour=14)
    world = WorldState()
    change = engine.on_sensor(SensorReading("distance", 10), world)  # near + close
    assert SetColor(0, 1, 1) in change  # excited = cyan
    assert any(isinstance(a, PlayTone) for a in change)  # chirps too
    angles = [a.angle for a in change if isinstance(a, SetServo)]
    angles += _servo_path(engine, world)
    assert 140 in angles  # it clearly swings up (a bounce)...
    assert max(angles) - min(angles) >= 40  # ...a big, readable motion, not a twitch


def test_nobody_present_droops_the_servo_low_and_goes_dark():
    engine = _engine(hour=14)
    world = WorldState()
    actions = engine.on_tick(world)  # not present -> away
    assert SetColor(0, 0, 0) in actions
    angles = [a.angle for a in actions if isinstance(a, SetServo)]
    angles += _servo_path(engine, world)
    assert min(angles) <= 45  # head droops low to rest


# -- webcam emotion driving the mood -----------------------------------------


def test_a_happy_face_turns_kivo_yellow_even_at_night():
    from kivo.vision import FakeEmotionSource

    face = FakeEmotionSource("happy")
    engine = MoodEngine(emotion=face, now=lambda: datetime(2026, 7, 30, 2, 0))
    assert SetColor(1, 1, 0) in engine.on_tick(WorldState())  # expression beats time


def test_a_sad_face_turns_kivo_blue():
    from kivo.vision import FakeEmotionSource

    face = FakeEmotionSource("sad")
    engine = MoodEngine(emotion=face, now=lambda: datetime(2026, 7, 30, 8, 0))
    assert SetColor(0, 0, 1) in engine.on_tick(WorldState())


def test_seeing_a_face_counts_as_presence_without_the_ultrasonic():
    from kivo.vision import FakeEmotionSource

    face = FakeEmotionSource("happy")  # no distance reading -> ultrasonic says away
    engine = MoodEngine(emotion=face, now=lambda: datetime(2026, 7, 30, 8, 0))
    colors = [a for a in engine.on_tick(WorldState()) if isinstance(a, SetColor)]
    assert SetColor(0, 0, 0) not in colors  # not "away": the face is present


def test_a_neutral_face_falls_back_to_the_environmental_mood():
    from kivo.vision import FakeEmotionSource

    face = FakeEmotionSource("neutral")
    engine = MoodEngine(
        emotion=face, now=lambda: datetime(2026, 7, 30, 8, 0), bright_above=700
    )
    world = WorldState()
    # A neutral face is present but expression-less -> environmental mood wins.
    actions = engine.on_sensor(SensorReading("light", 900), world)  # bright morning
    assert SetColor(1, 1, 0) in actions  # cheerful, not an emotion mood


def test_mood_only_changes_the_led_when_the_mood_changes():
    engine = _engine(hour=14)
    world = WorldState()
    engine.on_sensor(SensorReading("distance", 60), world)  # settle into a mood
    for _ in range(5):
        engine.on_tick(world)  # drain any chirp
    # A small wobble that doesn't change the mood emits nothing.
    assert engine.on_sensor(SensorReading("distance", 62), world) == []


# -- end to end through the Brain --------------------------------------------


class _OldFirmware(FakeTransport):
    """A board flashed before the expression handlers existed: it rejects the new
    ops as unknown, like running the new backend against stale firmware."""

    def _dispatch(self, cmd):
        op = cmd.body.split(" ", 1)[0]
        if op in ("LED.SET", "TONE.PLAY", "SERVO.SET"):
            self._respond_err(cmd.id, ErrorCode.UNKNOWN_OP, "unknown_op")
        else:
            super()._dispatch(cmd)


def test_brain_keeps_running_when_the_device_lacks_expression_support():
    transport = _OldFirmware()
    with DeviceClient(transport) as client:
        brain = Brain(
            client,
            [MoodEngine(now=lambda: datetime(2026, 7, 30, 8, 0))],
            sensors=["light", "presence", "distance"],
            poll_interval=0,
        )
        brain.start()
        transport.set_sensor("distance", 50)  # would trigger a colour + gesture
        for _ in range(3):
            brain.step()  # must not raise despite LED.SET being rejected
    assert transport.led == (0, 0, 0)  # capability disabled, but Kivo lived on


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
