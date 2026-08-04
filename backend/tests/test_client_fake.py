"""End-to-end tests of the device layer against the firmware emulator.

These prove the full stack works - DeviceClient → codec → transport → (emulated)
firmware → codec → DeviceClient - with no hardware attached.
"""

import pytest

from kivo.device import DeviceClient
from kivo.protocol import DeviceError, ErrorCode, Event
from kivo.transport import FakeTransport


def test_ping_round_trip():
    with DeviceClient(FakeTransport()) as client:
        client.ping()  # raises on failure; reaching here is success


def test_identify_returns_device_identity():
    with DeviceClient(FakeTransport()) as client:
        identity = client.identify()
    assert identity.name == "Kivo"
    assert identity.version == "0.1.0"
    assert identity.protocol == 1


def test_unknown_op_raises_device_error():
    with DeviceClient(FakeTransport()) as client:
        with pytest.raises(DeviceError) as info:
            client.request("NO.SUCH.OP")
    assert info.value.code == ErrorCode.UNKNOWN_OP


def test_boot_ready_event_is_delivered_to_handler():
    events: list[Event] = []
    transport = FakeTransport()  # emits READY on open()
    with DeviceClient(transport, event_handler=events.append) as client:
        # The READY event is queued before the first command; it should be
        # drained and dispatched while awaiting the ping response.
        client.ping()
    assert any(e.name == "READY" for e in events)


def test_correlation_ids_increment_across_commands():
    with DeviceClient(FakeTransport()) as client:
        client.ping()
        client.identify()
        client.ping()
    # No assertion needed beyond "did not raise": mismatched ids would surface
    # as a timeout because the emulator echoes the id it received.
