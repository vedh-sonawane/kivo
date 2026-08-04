"""CRC-8 tests. These values are the contract the firmware must reproduce."""

from kivo.protocol import crc8, crc8_hex


def test_empty_input_is_zero():
    assert crc8(b"") == 0x00


def test_known_vector_matches_smbus():
    # CRC-8/SMBUS of the ASCII digits "123456789" is 0xF4 - the standard
    # check value for this polynomial. If this fails, the algorithm is wrong.
    assert crc8(b"123456789") == 0xF4


def test_hex_is_two_uppercase_digits():
    assert crc8_hex(b"") == "00"
    value = crc8_hex(b"CMD 1 PING")
    assert len(value) == 2
    assert value == value.upper()


def test_single_bit_change_changes_crc():
    assert crc8(b"CMD 1 PING") != crc8(b"CMD 1 PINH")
