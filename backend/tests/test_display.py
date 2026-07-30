"""Display capability tests against the firmware emulator.

The fake transport keeps an inspectable in-memory screen, so we can assert what
the device *would* show without any hardware.
"""

import pytest

from kivo.device import DeviceClient
from kivo.protocol.errors import DeviceError, ErrorCode
from kivo.transport import FakeTransport


def test_write_places_text_at_origin_by_default():
    transport = FakeTransport()
    with DeviceClient(transport) as client:
        client.display_write("Hello")
    assert transport.screen[0].startswith("Hello")
    assert transport.screen[0] == "Hello".ljust(16)
    assert transport.screen[1] == " " * 16  # second row untouched


def test_write_honors_row_and_col():
    transport = FakeTransport()
    with DeviceClient(transport) as client:
        client.display_write("Kivo", row=1, col=2)
    assert transport.screen[1] == "  Kivo".ljust(16)


def test_write_truncates_at_row_edge():
    transport = FakeTransport()
    with DeviceClient(transport) as client:
        client.display_write("0123456789ABCDEFGHIJ", col=10)  # 10 + 20 > 16
    # Only the 6 columns from col=10..15 can hold text.
    assert transport.screen[0] == " " * 10 + "012345"


def test_clear_blanks_the_screen():
    transport = FakeTransport()
    with DeviceClient(transport) as client:
        client.display_write("something")
        client.display_clear()
    assert transport.screen == [" " * 16, " " * 16]


@pytest.mark.parametrize("row,col", [(2, 0), (0, 16), (-1, 0), (0, -1)])
def test_out_of_range_coordinates_raise_bad_args(row, col):
    with DeviceClient(FakeTransport()) as client:
        with pytest.raises(DeviceError) as info:
            client.display_write("x", row=row, col=col)
    assert info.value.code == ErrorCode.BAD_ARGS
