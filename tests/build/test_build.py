from __future__ import annotations

import pytest

from fdstk.patch.build import IPS_MAX_OFFSET, build_ips
from fdstk.patch.formats import PatchError, apply_ips


def test_a_patch_between_identical_files_changes_nothing() -> None:
    source = bytes(64)

    patch = build_ips(source, source)

    assert apply_ips(patch, source) == source


def test_a_patch_carries_one_record_per_run_of_changes() -> None:
    source = bytes(32)
    target = bytearray(source)
    target[4:8] = bytes([1, 2, 3, 4])
    target[20] = 0xFF

    patch = build_ips(source, bytes(target))

    assert apply_ips(patch, source) == bytes(target)


def test_a_patch_can_extend_the_file() -> None:
    source = bytes(16)
    target = source + bytes([0xAA]) * 8

    patch = build_ips(source, target)

    assert apply_ips(patch, source) == target


def test_a_patch_records_a_truncation() -> None:
    source = bytes([0x01]) * 32
    target = source[:16]

    patch = build_ips(source, target)

    assert apply_ips(patch, source) == target


def test_a_patch_opens_with_the_magic_and_ends_with_the_marker() -> None:
    patch = build_ips(bytes(8), bytes([0x01]) * 8)

    assert patch.startswith(b"PATCH")
    assert b"EOF" in patch


def test_a_source_too_large_for_the_format_is_refused() -> None:
    with pytest.raises(PatchError, match="too large"):
        build_ips(bytes(IPS_MAX_OFFSET + 2), bytes(IPS_MAX_OFFSET + 2))


def test_a_run_that_repeats_one_byte_becomes_a_short_record() -> None:
    source = bytes(4096)
    target = bytes([0xFF]) * 4096

    patch = build_ips(source, target)

    assert len(patch) < 100
    assert apply_ips(patch, source) == target


def test_a_change_at_the_reserved_offset_is_shifted_back_one_byte() -> None:
    source = bytearray(0x454F47)
    target = bytearray(source)
    target[0x454F46] = 0x01

    patch = build_ips(bytes(source), bytes(target))

    assert apply_ips(patch, bytes(source)) == bytes(target)


def test_a_change_that_reaches_the_end_of_the_file_is_recorded() -> None:
    source = bytes(16)
    target = bytes(12) + bytes([0x01, 0x02, 0x03, 0x04])

    patch = build_ips(source, target)

    assert apply_ips(patch, source) == target


def test_a_record_longer_than_the_format_allows_is_split() -> None:
    source = bytes(0x20000)
    target = bytes(bytearray(range(256)) * 512)

    patch = build_ips(source, target)

    assert apply_ips(patch, source) == target


def test_a_change_running_to_the_last_byte_is_recorded() -> None:
    source = bytes(8)
    target = bytes(4) + bytes([0x01, 0x02, 0x03, 0x04])

    assert apply_ips(build_ips(source, target), source) == target


def test_a_mixed_record_is_written_literally() -> None:
    source = bytes(8)
    target = bytes([0x01, 0x02, 0x03, 0x04, 0x00, 0x00, 0x00, 0x00])

    assert apply_ips(build_ips(source, target), source) == target


def test_a_target_shorter_than_the_source_records_the_truncation() -> None:
    source = bytes([0x01]) * 16
    target = bytes([0x01]) * 8

    patch = build_ips(source, target)

    assert apply_ips(patch, source) == target
    assert len(patch) > len(b"PATCHEOF")
