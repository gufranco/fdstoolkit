from __future__ import annotations

import zlib
from enum import StrEnum
from typing import Final

IPS_MAGIC: Final = b"PATCH"
IPS_END: Final = b"EOF"
UPS_MAGIC: Final = b"UPS1"
BPS_MAGIC: Final = b"BPS1"
OFFSET_SIZE: Final = 3
LENGTH_SIZE: Final = 2
FOOTER_SIZE: Final = 12
CRC_SIZE: Final = 4
CONTINUE_BIT: Final = 0x80
VALUE_MASK: Final = 0x7F
ACTION_MASK: Final = 0b11
SOURCE_READ: Final = 0
TARGET_READ: Final = 1
SOURCE_COPY: Final = 2


class PatchFormat(StrEnum):
    IPS = "ips"
    UPS = "ups"
    BPS = "bps"
    UNKNOWN = "unknown"


class PatchError(ValueError):
    pass


def detect_format(patch: bytes) -> PatchFormat:
    if patch.startswith(IPS_MAGIC):
        return PatchFormat.IPS
    if patch.startswith(UPS_MAGIC):
        return PatchFormat.UPS
    if patch.startswith(BPS_MAGIC):
        return PatchFormat.BPS
    return PatchFormat.UNKNOWN


def write_varint(value: int) -> bytes:
    out = bytearray()
    remaining = value
    while True:
        piece = remaining & VALUE_MASK
        remaining >>= 7
        if remaining == 0:
            out.append(CONTINUE_BIT | piece)
            break
        out.append(piece)
        remaining -= 1
    return bytes(out)


def read_varint(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    shift = 1
    cursor = position
    while cursor < len(data):
        byte = data[cursor]
        cursor += 1
        value += (byte & VALUE_MASK) * shift
        if byte & CONTINUE_BIT:
            return value, cursor
        shift <<= 7
        value += shift
    message = "the patch ended in the middle of a number"
    raise PatchError(message)


def _grow(out: bytearray, size: int) -> None:
    if len(out) < size:
        out.extend(bytes(size - len(out)))


def apply_ips(patch: bytes, source: bytes) -> bytes:
    if not patch.startswith(IPS_MAGIC):
        message = "not an IPS patch"
        raise PatchError(message)

    out = bytearray(source)
    cursor = len(IPS_MAGIC)
    while cursor + OFFSET_SIZE <= len(patch):
        marker = patch[cursor : cursor + len(IPS_END)]
        if marker == IPS_END:
            cursor += len(IPS_END)
            break
        offset = int.from_bytes(patch[cursor : cursor + OFFSET_SIZE], "big")
        cursor += OFFSET_SIZE
        length = int.from_bytes(patch[cursor : cursor + LENGTH_SIZE], "big")
        cursor += LENGTH_SIZE
        if length:
            chunk = patch[cursor : cursor + length]
            cursor += length
        else:
            count = int.from_bytes(patch[cursor : cursor + LENGTH_SIZE], "big")
            cursor += LENGTH_SIZE
            chunk = bytes([patch[cursor]]) * count
            cursor += 1
        _grow(out, offset + len(chunk))
        out[offset : offset + len(chunk)] = chunk

    if cursor + OFFSET_SIZE <= len(patch):
        out = out[: int.from_bytes(patch[cursor : cursor + OFFSET_SIZE], "big")]
    return bytes(out)


def _check_source(expected: int, source: bytes) -> None:
    actual = zlib.crc32(source)
    if actual != expected:
        message = (
            f"the source does not match the patch: expected CRC32 {expected:08x}, got {actual:08x}"
        )
        raise PatchError(message)


def apply_ups(patch: bytes, source: bytes) -> bytes:
    if not patch.startswith(UPS_MAGIC):
        message = "not a UPS patch"
        raise PatchError(message)

    body_end = len(patch) - FOOTER_SIZE
    _check_source(int.from_bytes(patch[body_end : body_end + CRC_SIZE], "little"), source)

    cursor = len(UPS_MAGIC)
    _, cursor = read_varint(patch, cursor)
    target_size, cursor = read_varint(patch, cursor)

    out = bytearray(source[:target_size])
    _grow(out, target_size)

    position = 0
    while cursor < body_end:
        skip, cursor = read_varint(patch, cursor)
        position += skip
        while cursor < body_end:
            value = patch[cursor]
            cursor += 1
            if value == 0:
                break
            if position < len(out):
                out[position] ^= value
            position += 1
        position += 1

    return bytes(out[:target_size])


def _bps_relative(patch: bytes, cursor: int, offset: int) -> tuple[int, int]:
    data, cursor = read_varint(patch, cursor)
    delta = data >> 1
    return offset + (-delta if data & 1 else delta), cursor


def apply_bps(patch: bytes, source: bytes) -> bytes:
    if not patch.startswith(BPS_MAGIC):
        message = "not a BPS patch"
        raise PatchError(message)

    body_end = len(patch) - FOOTER_SIZE
    _check_source(int.from_bytes(patch[body_end : body_end + CRC_SIZE], "little"), source)

    cursor = len(BPS_MAGIC)
    _, cursor = read_varint(patch, cursor)
    target_size, cursor = read_varint(patch, cursor)
    metadata_size, cursor = read_varint(patch, cursor)
    cursor += metadata_size

    out = bytearray()
    source_offset = 0
    target_offset = 0

    while cursor < body_end:
        data, cursor = read_varint(patch, cursor)
        action = data & ACTION_MASK
        length = (data >> 2) + 1

        if action == SOURCE_READ:
            start = len(out)
            out += source[start : start + length]
        elif action == TARGET_READ:
            out += patch[cursor : cursor + length]
            cursor += length
        elif action == SOURCE_COPY:
            source_offset, cursor = _bps_relative(patch, cursor, source_offset)
            out += source[source_offset : source_offset + length]
            source_offset += length
        else:
            target_offset, cursor = _bps_relative(patch, cursor, target_offset)
            for _ in range(length):
                out.append(out[target_offset])
                target_offset += 1

    return bytes(out[:target_size])
