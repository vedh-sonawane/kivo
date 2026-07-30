"""CRC-8 integrity check for Kivo Serial Protocol frames.

Polynomial 0x07, initial value 0x00, no reflection, no final XOR
(commonly "CRC-8/SMBUS"). This must match the firmware implementation in
``firmware/lib/kivo_protocol/kivo_protocol.cpp`` byte for byte.
"""

from __future__ import annotations

_POLYNOMIAL = 0x07


def crc8(data: bytes) -> int:
    """Return the CRC-8 of ``data`` as an integer in the range 0..255."""
    crc = 0x00
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ _POLYNOMIAL) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def crc8_hex(data: bytes) -> str:
    """Return the CRC-8 of ``data`` as two uppercase hex digits (e.g. ``"A3"``)."""
    return f"{crc8(data):02X}"
