from __future__ import annotations

import zlib

import pytest

from fdstk.patch.formats import (
    PatchError,
    PatchFormat,
    apply_bps,
    apply_ips,
    apply_ups,
    detect_format,
    read_varint,
    write_varint,
)


def ips(records: list[tuple[int, bytes]], *, truncate: int | None = None) -> bytes:
    out = bytearray(b"PATCH")
    for offset, payload in records:
        out += offset.to_bytes(3, "big")
        out += len(payload).to_bytes(2, "big")
        out += payload
    out += b"EOF"
    if truncate is not None:
        out += truncate.to_bytes(3, "big")
    return bytes(out)


def ips_rle(offset: int, count: int, value: int) -> bytes:
    return (
        b"PATCH"
        + offset.to_bytes(3, "big")
        + (0).to_bytes(2, "big")
        + count.to_bytes(2, "big")
        + bytes([value])
        + b"EOF"
    )


def test_an_ips_patch_is_detected() -> None:
    assert detect_format(ips([(0, b"A")])) is PatchFormat.IPS


def test_a_ups_patch_is_detected() -> None:
    assert detect_format(b"UPS1" + bytes(20)) is PatchFormat.UPS


def test_a_bps_patch_is_detected() -> None:
    assert detect_format(b"BPS1" + bytes(20)) is PatchFormat.BPS


def test_an_unknown_patch_is_reported() -> None:
    assert detect_format(b"nope") is PatchFormat.UNKNOWN


def test_an_ips_patch_replaces_bytes_at_an_offset() -> None:
    source = bytes(16)

    result = apply_ips(ips([(4, b"\xaa\xbb")]), source)

    assert result[4:6] == b"\xaa\xbb"
    assert len(result) == len(source)


def test_an_ips_patch_can_extend_the_file() -> None:
    result = apply_ips(ips([(8, b"\x01\x02")]), bytes(4))

    assert len(result) == 10
    assert result[8:] == b"\x01\x02"


def test_an_ips_run_length_record_repeats_a_byte() -> None:
    result = apply_ips(ips_rle(2, 5, 0xFF), bytes(10))

    assert result[2:7] == bytes([0xFF]) * 5


def test_an_ips_patch_can_truncate() -> None:
    result = apply_ips(ips([(0, b"\x01")], truncate=4), bytes(16))

    assert len(result) == 4


def test_an_ips_patch_without_its_magic_is_rejected() -> None:
    with pytest.raises(ValueError, match="not an IPS patch"):
        apply_ips(b"nope", bytes(4))


def test_a_varint_round_trips() -> None:
    for value in (0, 1, 127, 128, 255, 100000):
        assert read_varint(write_varint(value), 0)[0] == value


def test_a_ups_patch_applies_an_xor_difference() -> None:
    source = bytes([0x01, 0x02, 0x03, 0x04])
    target = bytes([0x01, 0xFF, 0x03, 0x04])

    patch = build_ups(source, target)

    assert apply_ups(patch, source) == target


def test_a_ups_patch_checks_the_source_crc() -> None:
    source = bytes([0x01, 0x02, 0x03, 0x04])
    patch = build_ups(source, bytes([0x01, 0xFF, 0x03, 0x04]))

    with pytest.raises(ValueError, match="source does not match"):
        apply_ups(patch, bytes([0x09, 0x09, 0x09, 0x09]))


def test_a_bps_patch_applies_a_source_copy_and_a_literal() -> None:
    source = bytes([0x10, 0x20, 0x30, 0x40])
    target = bytes([0x10, 0x20, 0xAA, 0xBB])

    patch = build_bps(source, target)

    assert apply_bps(patch, source) == target


def test_a_bps_patch_checks_the_source_crc() -> None:
    source = bytes([0x10, 0x20, 0x30, 0x40])
    patch = build_bps(source, bytes([0x10, 0x20, 0xAA, 0xBB]))

    with pytest.raises(ValueError, match="source does not match"):
        apply_bps(patch, bytes([0x00, 0x00, 0x00, 0x00]))


def build_ups(source: bytes, target: bytes) -> bytes:
    out = bytearray(b"UPS1")
    out += write_varint(len(source))
    out += write_varint(len(target))
    position = 0
    previous = 0
    while position < len(target):
        original = source[position] if position < len(source) else 0
        if original == target[position]:
            position += 1
            continue
        start = position
        chunk = bytearray()
        while position < len(target):
            original = source[position] if position < len(source) else 0
            if original == target[position]:
                break
            chunk.append(original ^ target[position])
            position += 1
        out += write_varint(start - previous)
        out += bytes(chunk)
        out += b"\x00"
        previous = position + 1
    out += zlib.crc32(source).to_bytes(4, "little")
    out += zlib.crc32(target).to_bytes(4, "little")
    out += zlib.crc32(bytes(out)).to_bytes(4, "little")
    return bytes(out)


def build_bps(source: bytes, target: bytes) -> bytes:
    body = bytearray()
    body += write_varint(len(source))
    body += write_varint(len(target))
    body += write_varint(0)

    common = 0
    while common < min(len(source), len(target)) and source[common] == target[common]:
        common += 1

    if common:
        body += write_varint(((common - 1) << 2) | 0)
    remaining = target[common:]
    if remaining:
        body += write_varint(((len(remaining) - 1) << 2) | 1)
        body += remaining

    out = bytearray(b"BPS1")
    out += body
    out += zlib.crc32(source).to_bytes(4, "little")
    out += zlib.crc32(target).to_bytes(4, "little")
    out += zlib.crc32(bytes(out)).to_bytes(4, "little")
    return bytes(out)


def test_a_truncated_varint_is_rejected() -> None:
    with pytest.raises(PatchError, match="ended in the middle"):
        read_varint(bytes([0x01, 0x02]), 0)


def test_a_ups_patch_without_its_magic_is_rejected() -> None:
    with pytest.raises(PatchError, match="not a UPS patch"):
        apply_ups(b"nope" + bytes(20), b"")


def test_a_bps_patch_without_its_magic_is_rejected() -> None:
    with pytest.raises(PatchError, match="not a BPS patch"):
        apply_bps(b"nope" + bytes(20), b"")


def test_a_bps_source_copy_reads_from_a_moved_offset() -> None:
    source = bytes([0x10, 0x20, 0x30, 0x40])
    body = bytearray()
    body += write_varint(len(source))
    body += write_varint(2)
    body += write_varint(0)
    body += write_varint(((2 - 1) << 2) | 2)
    body += write_varint(2 << 1)

    patch = bytearray(b"BPS1")
    patch += body
    patch += zlib.crc32(source).to_bytes(4, "little")
    patch += zlib.crc32(bytes([0x30, 0x40])).to_bytes(4, "little")
    patch += zlib.crc32(bytes(patch)).to_bytes(4, "little")

    assert apply_bps(bytes(patch), source) == bytes([0x30, 0x40])


def test_a_bps_target_copy_repeats_what_was_written() -> None:
    source = bytes([0xAA])
    body = bytearray()
    body += write_varint(len(source))
    body += write_varint(4)
    body += write_varint(0)
    body += write_varint(((2 - 1) << 2) | 1)
    body += bytes([0x01, 0x02])
    body += write_varint(((2 - 1) << 2) | 3)
    body += write_varint(0)

    patch = bytearray(b"BPS1")
    patch += body
    patch += zlib.crc32(source).to_bytes(4, "little")
    patch += zlib.crc32(bytes([0x01, 0x02, 0x01, 0x02])).to_bytes(4, "little")
    patch += zlib.crc32(bytes(patch)).to_bytes(4, "little")

    assert apply_bps(bytes(patch), source) == bytes([0x01, 0x02, 0x01, 0x02])


def test_a_bps_patch_can_carry_metadata() -> None:
    source = bytes([0x01, 0x02])
    metadata = b"<note/>"
    body = bytearray()
    body += write_varint(len(source))
    body += write_varint(2)
    body += write_varint(len(metadata))
    body += metadata
    body += write_varint(((2 - 1) << 2) | 0)

    patch = bytearray(b"BPS1")
    patch += body
    patch += zlib.crc32(source).to_bytes(4, "little")
    patch += zlib.crc32(source).to_bytes(4, "little")
    patch += zlib.crc32(bytes(patch)).to_bytes(4, "little")

    assert apply_bps(bytes(patch), source) == source


def test_a_ups_patch_can_extend_the_target() -> None:
    source = bytes([0x01])
    target = bytes([0x01, 0x55])
    patch = build_ups(source, target)

    assert apply_ups(patch, source) == target
