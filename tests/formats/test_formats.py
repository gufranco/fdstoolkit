from __future__ import annotations

import zlib

import pytest

from fdstoolkit.patch.formats import (
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
    # Arrange
    patch = ips([(0, b"A")])

    # Act
    result = detect_format(patch)

    # Assert
    assert result is PatchFormat.IPS


def test_a_ups_patch_is_detected() -> None:
    # Arrange
    patch = b"UPS1" + bytes(20)

    # Act
    result = detect_format(patch)

    # Assert
    assert result is PatchFormat.UPS


def test_a_bps_patch_is_detected() -> None:
    # Arrange
    patch = b"BPS1" + bytes(20)

    # Act
    result = detect_format(patch)

    # Assert
    assert result is PatchFormat.BPS


def test_an_unknown_patch_is_reported() -> None:
    # Arrange
    patch = b"nope"

    # Act
    result = detect_format(patch)

    # Assert
    assert result is PatchFormat.UNKNOWN


def test_an_ips_patch_replaces_bytes_at_an_offset() -> None:
    # Arrange
    source = bytes(16)

    # Act
    result = apply_ips(ips([(4, b"\xaa\xbb")]), source)

    # Assert
    assert result[4:6] == b"\xaa\xbb"
    assert len(result) == len(source)


def test_an_ips_patch_can_extend_the_file() -> None:
    # Arrange
    patch = ips([(8, b"\x01\x02")])
    source = bytes(4)

    # Act
    result = apply_ips(patch, source)

    # Assert
    assert len(result) == 10
    assert result[8:] == b"\x01\x02"


def test_an_ips_run_length_record_repeats_a_byte() -> None:
    # Arrange
    patch = ips_rle(2, 5, 0xFF)
    source = bytes(10)

    # Act
    result = apply_ips(patch, source)

    # Assert
    assert result[2:7] == bytes([0xFF]) * 5


def test_an_ips_patch_can_truncate() -> None:
    # Arrange
    patch = ips([(0, b"\x01")], truncate=4)
    source = bytes(16)

    # Act
    result = apply_ips(patch, source)

    # Assert
    assert len(result) == 4


def test_an_ips_patch_without_its_magic_is_rejected() -> None:
    # Arrange
    patch = b"nope"
    source = bytes(4)

    # Act
    with pytest.raises(ValueError, match="not an IPS patch") as raised:
        apply_ips(patch, source)

    # Assert
    assert raised.type is PatchError


def test_a_varint_round_trips() -> None:
    # Arrange
    values = (0, 1, 127, 128, 255, 100000)

    # Act
    decoded = [read_varint(write_varint(value), 0)[0] for value in values]

    # Assert
    assert decoded == list(values)


def test_a_ups_patch_applies_an_xor_difference() -> None:
    # Arrange
    source = bytes([0x01, 0x02, 0x03, 0x04])
    target = bytes([0x01, 0xFF, 0x03, 0x04])

    # Act
    patch = build_ups(source, target)

    # Assert
    assert apply_ups(patch, source) == target


def test_a_ups_patch_checks_the_source_crc() -> None:
    # Arrange
    source = bytes([0x01, 0x02, 0x03, 0x04])
    patch = build_ups(source, bytes([0x01, 0xFF, 0x03, 0x04]))

    # Act
    with pytest.raises(ValueError, match="source does not match") as raised:
        apply_ups(patch, bytes([0x09, 0x09, 0x09, 0x09]))

    # Assert
    assert raised.type is PatchError


def test_a_bps_patch_applies_a_source_copy_and_a_literal() -> None:
    # Arrange
    source = bytes([0x10, 0x20, 0x30, 0x40])
    target = bytes([0x10, 0x20, 0xAA, 0xBB])

    # Act
    patch = build_bps(source, target)

    # Assert
    assert apply_bps(patch, source) == target


def test_a_bps_patch_checks_the_source_crc() -> None:
    # Arrange
    source = bytes([0x10, 0x20, 0x30, 0x40])
    patch = build_bps(source, bytes([0x10, 0x20, 0xAA, 0xBB]))

    # Act
    with pytest.raises(ValueError, match="source does not match") as raised:
        apply_bps(patch, bytes([0x00, 0x00, 0x00, 0x00]))

    # Assert
    assert raised.type is PatchError


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
    # Arrange
    data = bytes([0x01, 0x02])
    position = 0

    # Act
    with pytest.raises(PatchError, match="ended in the middle") as raised:
        read_varint(data, position)

    # Assert
    assert raised.type is PatchError


def test_a_ups_patch_without_its_magic_is_rejected() -> None:
    # Arrange
    patch = b"nope" + bytes(20)
    source = b""

    # Act
    with pytest.raises(PatchError, match="not a UPS patch") as raised:
        apply_ups(patch, source)

    # Assert
    assert raised.type is PatchError


def test_a_bps_patch_without_its_magic_is_rejected() -> None:
    # Arrange
    patch = b"nope" + bytes(20)
    source = b""

    # Act
    with pytest.raises(PatchError, match="not a BPS patch") as raised:
        apply_bps(patch, source)

    # Assert
    assert raised.type is PatchError


def test_a_bps_source_copy_reads_from_a_moved_offset() -> None:
    # Arrange
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

    # Act
    patch += zlib.crc32(bytes(patch)).to_bytes(4, "little")

    # Assert
    assert apply_bps(bytes(patch), source) == bytes([0x30, 0x40])


def test_a_bps_target_copy_repeats_what_was_written() -> None:
    # Arrange
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

    # Act
    patch += zlib.crc32(bytes(patch)).to_bytes(4, "little")

    # Assert
    assert apply_bps(bytes(patch), source) == bytes([0x01, 0x02, 0x01, 0x02])


def test_a_bps_patch_can_carry_metadata() -> None:
    # Arrange
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

    # Act
    patch += zlib.crc32(bytes(patch)).to_bytes(4, "little")

    # Assert
    assert apply_bps(bytes(patch), source) == source


def test_a_ups_patch_can_extend_the_target() -> None:
    # Arrange
    source = bytes([0x01])
    target = bytes([0x01, 0x55])

    # Act
    patch = build_ups(source, target)

    # Assert
    assert apply_ups(patch, source) == target


def test_an_ips_patch_without_its_end_marker_stops_at_the_data() -> None:
    # Arrange
    expected = 0xAA

    # Act
    patch = b"PATCH" + (0).to_bytes(3, "big") + (1).to_bytes(2, "big") + b"\xaa"

    # Assert
    assert apply_ips(patch, bytes(4))[0] == expected


def test_a_ups_patch_whose_target_is_shorter_ignores_the_overflow() -> None:
    # Arrange
    source = bytes([0x01, 0x02, 0x03, 0x04])
    patch = bytearray(b"UPS1")
    patch += write_varint(len(source))
    patch += write_varint(2)
    patch += write_varint(0)
    patch += bytes([0xFF, 0xFF, 0xFF, 0xFF])
    patch += b"\x00"
    patch += zlib.crc32(source).to_bytes(4, "little")
    patch += zlib.crc32(bytes([0xFE, 0xFD])).to_bytes(4, "little")

    # Act
    patch += zlib.crc32(bytes(patch)).to_bytes(4, "little")

    # Assert
    assert apply_ups(bytes(patch), source) == bytes([0xFE, 0xFD])


def test_a_ups_patch_with_no_records_returns_the_source() -> None:
    # Arrange
    source = bytes([0x01, 0x02])
    patch = bytearray(b"UPS1")
    patch += write_varint(len(source))
    patch += write_varint(len(source))
    patch += zlib.crc32(source).to_bytes(4, "little")
    patch += zlib.crc32(source).to_bytes(4, "little")

    # Act
    patch += zlib.crc32(bytes(patch)).to_bytes(4, "little")

    # Assert
    assert apply_ups(bytes(patch), source) == source


def test_a_ups_record_that_runs_to_the_end_of_the_body_stops_there() -> None:
    # Arrange
    source = bytes([0x01, 0x02])
    patch = bytearray(b"UPS1")
    patch += write_varint(len(source))
    patch += write_varint(len(source))
    patch += write_varint(0)
    patch += bytes([0x03])
    patch += zlib.crc32(source).to_bytes(4, "little")
    patch += zlib.crc32(bytes([0x02, 0x02])).to_bytes(4, "little")

    # Act
    patch += zlib.crc32(bytes(patch)).to_bytes(4, "little")

    # Assert
    assert apply_ups(bytes(patch), source) == bytes([0x02, 0x02])


HUGE = 2**32


def bps(source: bytes, target_size: int, actions: bytes) -> bytes:
    patch = bytearray(b"BPS1")
    patch += write_varint(len(source)) + write_varint(target_size) + write_varint(0) + actions
    patch += zlib.crc32(source).to_bytes(4, "little")
    patch += bytes(4)
    patch += zlib.crc32(bytes(patch)).to_bytes(4, "little")
    return bytes(patch)


def test_a_bps_target_copy_past_the_target_is_refused_before_it_runs() -> None:
    # Arrange
    source = bytes([0xAA])
    actions = (
        write_varint(((1 - 1) << 2) | 1)
        + bytes([0x01])
        + write_varint(((HUGE - 1) << 2) | 3)
        + write_varint(0)
    )

    # Act
    with pytest.raises(PatchError, match="past the 16 bytes") as raised:
        apply_bps(bps(source, 16, actions), source)

    # Assert
    assert raised.type is PatchError


def test_a_bps_target_copy_from_where_nothing_was_written_is_refused() -> None:
    # Arrange
    source = bytes([0xAA])
    actions = write_varint(((1 - 1) << 2) | 1) + bytes([0x01]) + write_varint(((1 - 1) << 2) | 3)
    actions += write_varint(8 << 1)

    # Act
    with pytest.raises(PatchError, match="copies from") as raised:
        apply_bps(bps(source, 4, actions), source)

    # Assert
    assert raised.type is PatchError


def test_a_patch_asking_for_a_target_larger_than_any_image_is_refused() -> None:
    # Arrange
    source = bytes([0xAA])

    # Act
    with pytest.raises(PatchError, match="larger than any disk image") as raised:
        apply_bps(bps(source, HUGE, b""), source)

    # Assert
    assert raised.type is PatchError


def test_an_ips_run_length_record_cut_short_is_a_patch_error() -> None:
    # Arrange
    patch = b"PATCH" + (0).to_bytes(3, "big") + (0).to_bytes(2, "big") + (4).to_bytes(2, "big")

    # Act
    with pytest.raises(PatchError, match="ends inside a record") as raised:
        apply_ips(patch, bytes(8))

    # Assert
    assert raised.type is PatchError


def test_an_ips_record_whose_data_is_cut_short_is_a_patch_error() -> None:
    # Arrange
    patch = b"PATCH" + (0).to_bytes(3, "big") + (8).to_bytes(2, "big") + b"\x01\x02"

    # Act
    with pytest.raises(PatchError, match="ends inside a record") as raised:
        apply_ips(patch, bytes(8))

    # Assert
    assert raised.type is PatchError


def test_a_bps_source_read_past_the_source_is_refused() -> None:
    # Arrange
    source = bytes([0xAA])

    # Act
    with pytest.raises(
        PatchError, match="reads 4 bytes at byte 0 of a source 1 bytes long"
    ) as raised:
        apply_bps(bps(source, 4, write_varint(((4 - 1) << 2) | 0)), source)

    # Assert
    assert raised.type is PatchError


def test_a_bps_source_copy_from_before_the_source_is_refused() -> None:
    # Arrange
    source = bytes([0xAA, 0xBB])
    actions = write_varint(((1 - 1) << 2) | 2) + write_varint((3 << 1) | 1)

    # Act
    with pytest.raises(PatchError, match="at byte -3") as raised:
        apply_bps(bps(source, 1, actions), source)

    # Assert
    assert raised.type is PatchError


def resealed(patch: bytes, *, target_crc: int) -> bytes:
    body = patch[: -2 * 4] + target_crc.to_bytes(4, "little")
    return body + zlib.crc32(body).to_bytes(4, "little")


def test_a_ups_patch_with_a_damaged_byte_is_refused_by_its_own_checksum() -> None:
    # Arrange
    source = bytes([0x01, 0x02, 0x03, 0x04])
    patch = bytearray(build_ups(source, bytes([0x01, 0xFF, 0x03, 0x04])))
    patch[len(b"UPS1") + 2] ^= 0x01

    # Act
    with pytest.raises(PatchError, match="the patch is damaged") as raised:
        apply_ups(bytes(patch), source)

    # Assert
    assert raised.type is PatchError


def test_a_ups_patch_whose_result_misses_its_target_checksum_is_refused() -> None:
    # Arrange
    source = bytes([0x01, 0x02, 0x03, 0x04])
    patch = resealed(build_ups(source, bytes([0x01, 0xFF, 0x03, 0x04])), target_crc=0x1234)

    # Act
    with pytest.raises(PatchError, match="expected CRC32 00001234") as raised:
        apply_ups(patch, source)

    # Assert
    assert raised.type is PatchError


def test_a_bps_patch_whose_result_misses_its_target_checksum_is_refused() -> None:
    # Arrange
    source = bytes([0x10, 0x20, 0x30, 0x40])
    patch = resealed(build_bps(source, bytes([0x10, 0x20, 0xAA, 0xBB])), target_crc=0x5678)

    # Act
    with pytest.raises(PatchError, match="expected CRC32 00005678") as raised:
        apply_bps(patch, source)

    # Assert
    assert raised.type is PatchError


def test_a_patch_too_short_for_its_checksums_is_refused() -> None:
    # Arrange
    patch = b"BPS1" + bytes(4)

    # Act
    with pytest.raises(PatchError, match="too short to carry its three checksums") as raised:
        apply_bps(patch, b"")

    # Assert
    assert raised.type is PatchError


def test_a_bps_literal_that_runs_into_the_checksums_is_refused() -> None:
    # Arrange
    source = bytes([0xAA])
    patch = bps(source, 4, write_varint(((4 - 1) << 2) | 1) + bytes([0x01]))

    # Act
    with pytest.raises(PatchError, match="ends inside a record") as raised:
        apply_bps(patch, source)

    # Assert
    assert raised.type is PatchError
