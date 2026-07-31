"""Codec tests: framing, CRC verification, and round-tripping."""

import pytest

from kivo import protocol as codec
from kivo.protocol import Frame, FrameType, ProtocolError


def test_encode_ping_command():
    line = codec.encode(Frame(FrameType.CMD, 1, "PING"))
    assert line.startswith("CMD 1 PING*")
    payload, _, crc = line.partition("*")
    assert payload == "CMD 1 PING"
    assert len(crc) == 2


@pytest.mark.parametrize(
    "frame",
    [
        Frame(FrameType.CMD, 1, "PING"),
        Frame(FrameType.CMD, 42, "SYS.IDENTIFY"),
        Frame(FrameType.CMD, 7, "DISPLAY.WRITE Hello World"),
        Frame(FrameType.RES, 1, "OK PONG"),
        Frame(FrameType.RES, 3, "ERR 3 unknown_op"),
        Frame(FrameType.EVT, 0, "READY Kivo 0.1.0 1"),
    ],
)
def test_round_trip(frame):
    assert codec.decode(codec.encode(frame)) == frame


def test_body_with_spaces_is_preserved():
    frame = Frame(FrameType.CMD, 9, "DISPLAY.WRITE a b c")
    assert codec.decode(codec.encode(frame)).body == "DISPLAY.WRITE a b c"


def test_decode_rejects_bad_crc():
    line = codec.encode(Frame(FrameType.CMD, 1, "PING"))
    corrupted = line[:-2] + "00"  # clobber the checksum
    with pytest.raises(ProtocolError, match="CRC"):
        codec.decode(corrupted)


def test_decode_rejects_missing_checksum():
    with pytest.raises(ProtocolError, match="checksum"):
        codec.decode("CMD 1 PING")


def test_decode_rejects_unknown_type():
    # Build a valid checksum over a bogus type so we exercise the type check,
    # not the CRC check.
    from kivo.protocol import crc8_hex

    payload = "XXX 1 PING"
    line = f"{payload}*{crc8_hex(payload.encode())}"
    with pytest.raises(ProtocolError, match="frame type"):
        codec.decode(line)


def test_encode_rejects_reserved_char_in_body():
    with pytest.raises(ProtocolError, match="reserved"):
        codec.encode(Frame(FrameType.CMD, 1, "PING*oops"))


def test_encode_rejects_oversize_line():
    with pytest.raises(ProtocolError, match="exceeds"):
        codec.encode(Frame(FrameType.CMD, 1, "X" * 80))
