"""Tests for the button: tap / double-tap / hold gestures and their reactions."""

from kivo.brain import (
    Behavior,
    Brain,
    ButtonEvent,
    SetColor,
    ShowText,
    WorldState,
)
from kivo.device import DeviceClient, SensorReading
from kivo.transport import FakeTransport


def _tap(button, world, clock, down, up):
    clock[0] = down
    button.on_sensor(SensorReading("button", 1), world)
    clock[0] = up
    return button.on_sensor(SensorReading("button", 0), world)


def _button(clock):
    return ButtonEvent(long_press=0.7, double_window=0.3, clock=lambda: clock[0])


def test_a_tap_pets_kivo():
    clock = [0.0]
    button = _button(clock)
    world = WorldState()
    assert _tap(button, world, clock, 0.0, 0.1) == []  # a tap waits for a 2nd
    clock[0] = 0.2
    assert button.on_tick(world) == []  # still inside the double-tap window
    clock[0] = 0.5  # window passed -> confirmed single tap
    actions = button.on_tick(world)
    assert SetColor(1, 0, 1) in actions  # magenta pet
    assert ShowText(0, "hehe :)") in actions


def test_a_double_tap_makes_kivo_dance():
    clock = [0.0]
    button = _button(clock)
    world = WorldState()
    assert _tap(button, world, clock, 0.0, 0.05) == []  # first tap
    actions = _tap(button, world, clock, 0.15, 0.2)  # second tap within window
    assert SetColor(0, 1, 1) in actions  # cyan dance
    assert ShowText(0, "wheee!") in actions
    # And it does NOT also fire a single-tap pet afterwards.
    clock[0] = 1.0
    later = []
    for _ in range(8):
        later += button.on_tick(world)
    assert SetColor(1, 0, 1) not in later  # never the pet magenta after a dance


def test_a_hold_shushes_kivo():
    clock = [0.0]
    button = _button(clock)
    world = WorldState()
    actions = _tap(button, world, clock, 0.0, 1.0)  # held for a full second
    assert SetColor(0, 0, 0) in actions  # calm: LED off
    assert ShowText(0, "resting") in actions


def test_button_events_reach_behaviors_through_the_brain():
    class Recorder(Behavior):
        def __init__(self):
            self.seen = []

        def on_sensor(self, reading, world):
            self.seen.append((reading.name, reading.value))
            return []

    recorder = Recorder()
    transport = FakeTransport()
    with DeviceClient(transport) as client:
        brain = Brain(client, [recorder], sensors=[], poll_interval=0)
        brain.start()
        transport.press_button(True)  # the button auto-streams, no subscribe
        transport.press_button(False)
        brain.step()
    assert ("button", 1) in recorder.seen
    assert ("button", 0) in recorder.seen
