from __future__ import annotations

import zlib
from dataclasses import dataclass, replace
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
VARINT_BITS: Final = 7
ACTION_MASK: Final = 0b11
SOURCE_READ: Final = 0
TARGET_READ: Final = 1
SOURCE_COPY: Final = 2
TARGET_COPY: Final = 3
MAX_TARGET_BYTES: Final = 16 * 1024 * 1024


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
    while remaining > VALUE_MASK:
        out.append(remaining & VALUE_MASK)
        remaining = (remaining >> VARINT_BITS) - 1
    out.append(CONTINUE_BIT | remaining)
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
        shift <<= VARINT_BITS
        value += shift
    message = "the patch ended in the middle of a number"
    raise PatchError(message)


def _cut_short(patch: bytes, end: int, cursor: int) -> None:
    if end > len(patch):
        message = f"the patch ends inside a record at byte {cursor}"
        raise PatchError(message)


def _target_size(value: int) -> int:
    if value > MAX_TARGET_BYTES:
        message = (
            f"the patch declares a {value}-byte target, larger than any disk image; "
            f"the limit is {MAX_TARGET_BYTES} bytes"
        )
        raise PatchError(message)
    return value


def _ips_record(patch: bytes, cursor: int) -> tuple[int, bytes, int]:
    offset = int.from_bytes(patch[cursor : cursor + OFFSET_SIZE], "big")
    start = cursor + OFFSET_SIZE + LENGTH_SIZE
    length = int.from_bytes(patch[cursor + OFFSET_SIZE : start], "big")
    if length:
        _cut_short(patch, start + length, start)
        return offset, patch[start : start + length], start + length
    _cut_short(patch, start + LENGTH_SIZE + 1, start)
    count = int.from_bytes(patch[start : start + LENGTH_SIZE], "big")
    return offset, bytes([patch[start + LENGTH_SIZE]]) * count, start + LENGTH_SIZE + 1


def _ips_records(patch: bytes) -> tuple[list[tuple[int, bytes]], int]:
    records: list[tuple[int, bytes]] = []
    cursor = len(IPS_MAGIC)
    while cursor + OFFSET_SIZE <= len(patch) and patch[cursor : cursor + len(IPS_END)] != IPS_END:
        offset, chunk, cursor = _ips_record(patch, cursor)
        records.append((offset, chunk))
    ended = patch[cursor : cursor + len(IPS_END)] == IPS_END
    return records, cursor + (len(IPS_END) if ended else 0)


def apply_ips(patch: bytes, source: bytes) -> bytes:
    if not patch.startswith(IPS_MAGIC):
        message = "not an IPS patch"
        raise PatchError(message)
    records, cursor = _ips_records(patch)
    out = bytearray(source)
    for offset, chunk in records:
        end = offset + len(chunk)
        out.extend(bytes(max(end - len(out), 0)))
        out[offset:end] = chunk
    if cursor + OFFSET_SIZE <= len(patch):
        return bytes(out[: int.from_bytes(patch[cursor : cursor + OFFSET_SIZE], "big")])
    return bytes(out)


def _check_source(expected: int, source: bytes) -> None:
    actual = zlib.crc32(source)
    if actual != expected:
        message = (
            f"the source does not match the patch: expected CRC32 {expected:08x}, got {actual:08x}"
        )
        raise PatchError(message)


def _footer(patch: bytes) -> tuple[int, int, int]:
    body_end = len(patch) - FOOTER_SIZE
    if body_end < 0:
        message = f"the patch is {len(patch)} bytes, too short to carry its three checksums"
        raise PatchError(message)
    stored = int.from_bytes(patch[-CRC_SIZE:], "little")
    actual = zlib.crc32(patch[:-CRC_SIZE])
    if actual != stored:
        message = (
            f"the patch is damaged: its own CRC32 is {stored:08x} and its bytes give {actual:08x}"
        )
        raise PatchError(message)
    source = int.from_bytes(patch[body_end : body_end + CRC_SIZE], "little")
    target = int.from_bytes(patch[body_end + CRC_SIZE : body_end + 2 * CRC_SIZE], "little")
    return body_end, source, target


def _checked_target(expected: int, target: bytes) -> bytes:
    actual = zlib.crc32(target)
    if actual != expected:
        message = (
            f"the patched image does not match the patch: expected CRC32 {expected:08x}, "
            f"got {actual:08x}"
        )
        raise PatchError(message)
    return target


def _ups_hunks(patch: bytes, cursor: int, body_end: int) -> list[tuple[int, bytes]]:
    hunks: list[tuple[int, bytes]] = []
    position = 0
    while cursor < body_end:
        skip, cursor = read_varint(patch, cursor)
        position += skip
        found = patch.find(b"\0", cursor, body_end)
        end = body_end if found < 0 else found
        hunks.append((position, patch[cursor:end]))
        position += end - cursor + 1
        cursor = end + 1
    return hunks


def _xored(base: bytes, hunks: list[tuple[int, bytes]]) -> bytes:
    out = bytearray(base)
    for position, data in hunks:
        for offset, value in enumerate(data[: max(len(out) - position, 0)]):
            out[position + offset] ^= value
    return bytes(out)


def apply_ups(patch: bytes, source: bytes) -> bytes:
    if not patch.startswith(UPS_MAGIC):
        message = "not a UPS patch"
        raise PatchError(message)
    body_end, source_crc, target_crc = _footer(patch)
    _check_source(source_crc, source)
    _, cursor = read_varint(patch, len(UPS_MAGIC))
    declared, cursor = read_varint(patch, cursor)
    target_size = _target_size(declared)
    base = source[:target_size].ljust(target_size, b"\0")
    return _checked_target(target_crc, _xored(base, _ups_hunks(patch, cursor, body_end)))


def _bps_relative(patch: bytes, cursor: int, offset: int) -> tuple[int, int]:
    data, cursor = read_varint(patch, cursor)
    delta = data >> 1
    return offset + (-delta if data & 1 else delta), cursor


def _room(out: bytearray, length: int, target_size: int) -> None:
    if len(out) + length > target_size:
        message = f"the patch writes past the {target_size} bytes its target holds"
        raise PatchError(message)


def _in_source(source: bytes, offset: int, length: int) -> None:
    if offset < 0 or offset + length > len(source):
        message = (
            f"the patch reads {length} bytes at byte {offset} of a source {len(source)} bytes long"
        )
        raise PatchError(message)


def _written(out: bytes | bytearray, offset: int) -> None:
    if not 0 <= offset < len(out):
        message = f"the patch copies from byte {offset} of a target {len(out)} bytes long"
        raise PatchError(message)


@dataclass(frozen=True, slots=True)
class _BpsStep:
    patch: bytes
    body_end: int
    source: bytes
    cursor: int
    length: int
    source_offset: int
    target_offset: int


def _target_copy(out: bytes | bytearray, offset: int, length: int) -> bytes:
    produced = bytearray()
    for index in range(length):
        at = offset + index
        produced.append(out[at] if at < len(out) else produced[at - len(out)])
    return bytes(produced)


def _source_read(step: _BpsStep, out: bytes | bytearray) -> tuple[bytes, _BpsStep]:
    _in_source(step.source, len(out), step.length)
    return step.source[len(out) : len(out) + step.length], step


def _target_read(step: _BpsStep, out: bytes | bytearray) -> tuple[bytes, _BpsStep]:
    del out
    _cut_short(step.patch[: step.body_end], step.cursor + step.length, step.cursor)
    end = step.cursor + step.length
    return step.patch[step.cursor : end], replace(step, cursor=end)


def _source_copy(step: _BpsStep, out: bytes | bytearray) -> tuple[bytes, _BpsStep]:
    del out
    offset, cursor = _bps_relative(step.patch, step.cursor, step.source_offset)
    _in_source(step.source, offset, step.length)
    moved = replace(step, cursor=cursor, source_offset=offset + step.length)
    return step.source[offset : offset + step.length], moved


def _target_copied(step: _BpsStep, out: bytes | bytearray) -> tuple[bytes, _BpsStep]:
    offset, cursor = _bps_relative(step.patch, step.cursor, step.target_offset)
    _written(out, offset)
    moved = replace(step, cursor=cursor, target_offset=offset + step.length)
    return _target_copy(out, offset, step.length), moved


BPS_ACTIONS: Final = {
    SOURCE_READ: _source_read,
    TARGET_READ: _target_read,
    SOURCE_COPY: _source_copy,
    TARGET_COPY: _target_copied,
}


def _bps_start(patch: bytes) -> tuple[int, int]:
    _, cursor = read_varint(patch, len(BPS_MAGIC))
    declared, cursor = read_varint(patch, cursor)
    metadata_size, cursor = read_varint(patch, cursor)
    return cursor + metadata_size, _target_size(declared)


def apply_bps(patch: bytes, source: bytes) -> bytes:
    if not patch.startswith(BPS_MAGIC):
        message = "not a BPS patch"
        raise PatchError(message)
    body_end, source_crc, target_crc = _footer(patch)
    _check_source(source_crc, source)
    cursor, target_size = _bps_start(patch)
    out = bytearray()
    step = _BpsStep(patch, body_end, source, cursor, 0, 0, 0)
    while step.cursor < body_end:
        data, cursor = read_varint(patch, step.cursor)
        step = replace(step, cursor=cursor, length=(data >> 2) + 1)
        _room(out, step.length, target_size)
        produced, step = BPS_ACTIONS[data & ACTION_MASK](step, out)
        out += produced
    return _checked_target(target_crc, bytes(out[:target_size]))
