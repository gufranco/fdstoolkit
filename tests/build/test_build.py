from __future__ import annotations

import pytest

from fdstoolkit.patch.build import IPS_MAX_OFFSET, build_ips
from fdstoolkit.patch.formats import PatchError, apply_ips


def test_a_patch_between_identical_files_changes_nothing() -> None:
    # Arrange
    source = bytes(64)

    # Act
    patch = build_ips(source, source)

    # Assert
    assert apply_ips(patch, source) == source


def test_a_patch_carries_one_record_per_run_of_changes() -> None:
    # Arrange
    source = bytes(32)
    target = bytearray(source)
    target[4:8] = bytes([1, 2, 3, 4])
    target[20] = 0xFF

    # Act
    patch = build_ips(source, bytes(target))

    # Assert
    assert apply_ips(patch, source) == bytes(target)


def test_a_patch_can_extend_the_file() -> None:
    # Arrange
    source = bytes(16)
    target = source + bytes([0xAA]) * 8

    # Act
    patch = build_ips(source, target)

    # Assert
    assert apply_ips(patch, source) == target


def test_a_patch_records_a_truncation() -> None:
    # Arrange
    source = bytes([0x01]) * 32
    target = source[:16]

    # Act
    patch = build_ips(source, target)

    # Assert
    assert apply_ips(patch, source) == target


def test_a_patch_opens_with_the_magic_and_ends_with_the_marker() -> None:
    # Arrange
    source = bytes(8)
    target = bytes([0x01]) * 8

    # Act
    patch = build_ips(source, target)

    # Assert
    assert patch.startswith(b"PATCH")
    assert b"EOF" in patch


def test_a_source_too_large_for_the_format_is_refused() -> None:
    # Arrange
    source = bytes(IPS_MAX_OFFSET + 2)
    target = bytes(IPS_MAX_OFFSET + 2)

    # Act
    with pytest.raises(PatchError, match="too large") as raised:
        build_ips(source, target)

    # Assert
    assert raised.type is PatchError


def test_a_run_that_repeats_one_byte_becomes_a_short_record() -> None:
    # Arrange
    source = bytes(4096)
    target = bytes([0xFF]) * 4096

    # Act
    patch = build_ips(source, target)

    # Assert
    assert len(patch) < 100
    assert apply_ips(patch, source) == target


def test_a_change_at_the_reserved_offset_is_shifted_back_one_byte() -> None:
    # Arrange
    source = bytearray(0x454F47)
    target = bytearray(source)
    target[0x454F46] = 0x01

    # Act
    patch = build_ips(bytes(source), bytes(target))

    # Assert
    assert apply_ips(patch, bytes(source)) == bytes(target)


def test_a_change_that_reaches_the_end_of_the_file_is_recorded() -> None:
    # Arrange
    source = bytes(16)
    target = bytes(12) + bytes([0x01, 0x02, 0x03, 0x04])

    # Act
    patch = build_ips(source, target)

    # Assert
    assert apply_ips(patch, source) == target


def test_a_record_longer_than_the_format_allows_is_split() -> None:
    # Arrange
    source = bytes(0x20000)
    target = bytes(bytearray(range(256)) * 512)

    # Act
    patch = build_ips(source, target)

    # Assert
    assert apply_ips(patch, source) == target


def test_a_change_running_to_the_last_byte_is_recorded() -> None:
    # Arrange
    source = bytes(8)

    # Act
    target = bytes(4) + bytes([0x01, 0x02, 0x03, 0x04])

    # Assert
    assert apply_ips(build_ips(source, target), source) == target


def test_a_mixed_record_is_written_literally() -> None:
    # Arrange
    source = bytes(8)

    # Act
    target = bytes([0x01, 0x02, 0x03, 0x04, 0x00, 0x00, 0x00, 0x00])

    # Assert
    assert apply_ips(build_ips(source, target), source) == target


def test_a_target_shorter_than_the_source_records_the_truncation() -> None:
    # Arrange
    source = bytes([0x01]) * 16
    target = bytes([0x01]) * 8

    # Act
    patch = build_ips(source, target)

    # Assert
    assert apply_ips(patch, source) == target
    assert len(patch) > len(b"PATCHEOF")
