from __future__ import annotations

import zlib

import pytest
from formats_kit import HUGE, bps, build_ups, ips, ips_rle, resealed

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


def test_a_patch_too_short_for_its_checksums_is_refused() -> None:
    # Arrange
    patch = b"BPS1" + bytes(4)

    # Act
    with pytest.raises(PatchError, match="too short to carry its three checksums") as raised:
        apply_bps(patch, b"")

    # Assert
    assert raised.type is PatchError
