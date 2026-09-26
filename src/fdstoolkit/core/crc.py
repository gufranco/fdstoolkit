from __future__ import annotations

from collections.abc import Callable
from typing import Final

POLYNOMIAL: Final = 0x8408
INITIAL: Final = 0x8000
CRC_SIZE: Final = 2
MASK: Final = 0xFFFF


def _feed(state: int, byte: int) -> int:
    state |= byte << 16
    for _ in range(8):
        if state & 1:
            state ^= POLYNOMIAL << 1
        state >>= 1
    return state


def _finish(state: int) -> int:
    for _ in range(CRC_SIZE):
        state = _feed(state, 0)
    return state & MASK


def block_crc(data: bytes) -> int:
    state = INITIAL
    for byte in data:
        state = _feed(state, byte)
    return _finish(state)


def prefix_crcs(data: bytes) -> tuple[int, ...]:
    state = INITIAL
    found = [_finish(state)]
    for byte in data:
        state = _feed(state, byte)
        found.append(_finish(state))
    return tuple(found)


def _anywhere(size: int) -> bool:
    del size
    return True


def crc_boundary(
    data: bytes, sizes: range, accept: Callable[[int], bool] = _anywhere
) -> int | None:
    crcs = prefix_crcs(data[: max(len(data) - CRC_SIZE, 0)])
    for size in range(sizes.start, min(sizes.stop, len(crcs))):
        if crcs[size] == decode_crc(data[size : size + CRC_SIZE]) and accept(size):
            return size
    return None


def encode_crc(value: int) -> bytes:
    return bytes((value & 0xFF, (value >> 8) & 0xFF))


def decode_crc(data: bytes) -> int:
    if len(data) < CRC_SIZE:
        message = f"a CRC needs {CRC_SIZE} bytes, got {len(data)}"
        raise ValueError(message)
    return data[0] | (data[1] << 8)
