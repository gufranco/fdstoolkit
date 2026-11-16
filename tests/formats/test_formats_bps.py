from __future__ import annotations

import zlib

import pytest
from formats_kit import HUGE, bps, build_bps, resealed

from fdstoolkit.patch.formats import (
    PatchError,
    PatchFormat,
    apply_bps,
    detect_format,
    write_varint,
)


def test_a_bps_patch_is_detected() -> None:
    # Arrange
    patch = b"BPS1" + bytes(20)

    # Act
    result = detect_format(patch)

    # Assert
    assert result is PatchFormat.BPS


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


def test_a_bps_patch_whose_result_misses_its_target_checksum_is_refused() -> None:
    # Arrange
    source = bytes([0x10, 0x20, 0x30, 0x40])
    patch = resealed(build_bps(source, bytes([0x10, 0x20, 0xAA, 0xBB])), target_crc=0x5678)

    # Act
    with pytest.raises(PatchError, match="expected CRC32 00005678") as raised:
        apply_bps(patch, source)

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
