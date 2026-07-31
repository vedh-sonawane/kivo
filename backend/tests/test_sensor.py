"""Sensor capability tests against the firmware emulator."""

import pytest

from kivo.device import DeviceClient, SensorReading
from kivo.protocol import DeviceError, ErrorCode
from kivo.transport import FakeTransport


def test_read_returns_current_value():
    transport = FakeTransport()
    transport_value = 512  # emulator's default for "light"
    with DeviceClient(transport) as client:
        reading = client.sensor_read("light")
    assert reading == SensorReading(name="light", value=transport_value)


def test_read_unknown_sensor_raises_bad_args():
    with DeviceClient(FakeTransport()) as client:
        with pytest.raises(DeviceError) as info:
            client.sensor_read("nope")
    assert info.value.code == ErrorCode.BAD_ARGS


def test_subscribe_streams_initial_reading():
    events = []
    transport = FakeTransport()
    with DeviceClient(transport, event_handler=events.append) as client:
        client.subscribe_sensor("light")
        client.pump_events()  # drain the initial reading queued after the ack
    readings = [DeviceClient.parse_sensor_event(e) for e in events]
    assert SensorReading("light", 512) in readings


def test_changed_value_emits_stream_event_while_subscribed():
    events = []
    transport = FakeTransport()
    with DeviceClient(transport, event_handler=events.append) as client:
        client.subscribe_sensor("light")
        transport.set_sensor("light", 900)  # simulate the device streaming a change
        client.pump_events()
    readings = [DeviceClient.parse_sensor_event(e) for e in events]
    assert SensorReading("light", 900) in readings


def test_unsubscribe_stops_the_stream():
    events = []
    transport = FakeTransport()
    with DeviceClient(transport, event_handler=events.append) as client:
        client.subscribe_sensor("light")
        client.pump_events()  # consume initial reading
        client.unsubscribe_sensor("light")
        events.clear()
        transport.set_sensor("light", 123)  # no longer subscribed -> no event
        client.pump_events()
    assert events == []
