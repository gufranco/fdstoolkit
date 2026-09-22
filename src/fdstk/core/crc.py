from __future__ import annotations

from typing import Final

POLYNOMIAL: Final = 0x8408
INITIAL: Final = 0x8000
CRC_SIZE: Final = 2
MASK: Final = 0xFFFF


def block_crc(data: bytes) -> int:
    state = INITIAL
    for byte in data + bytes(CRC_SIZE):
        state |= byte << 16
        for _ in range(8):
            if state & 1:
                state ^= POLYNOMIAL << 1
            state >>= 1
    return state & MASK


def encode_crc(value: int) -> bytes:
    return bytes((value & 0xFF, (value >> 8) & 0xFF))


def decode_crc(data: bytes) -> int:
    if len(data) < CRC_SIZE:
        message = f"a CRC needs {CRC_SIZE} bytes, got {len(data)}"
        raise ValueError(message)
    return data[0] | (data[1] << 8)
