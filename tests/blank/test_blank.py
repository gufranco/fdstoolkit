from __future__ import annotations

import hashlib

import pytest

from fdstoolkit.build.blank import (
    REFERENCE_BLANK_64_SHA256,
    REFERENCE_BLANK_128_SHA256,
    blank_image,
)
from fdstoolkit.codecs.fds import SIDE_SIZE, decode
from fdstoolkit.core.diskinfo import DiskInfo
from fdstoolkit.identify.provenance import Origin, provenance_of


def test_an_unformatted_single_side_matches_the_reference_blank() -> None:
    data = blank_image(sides=1, headered=True, formatted=False)

    assert len(data) == 16 + SIDE_SIZE
    assert hashlib.sha256(data).hexdigest() == REFERENCE_BLANK_64_SHA256


def test_an_unformatted_two_side_disk_matches_the_reference_blank() -> None:
    data = blank_image(sides=2, headered=True, formatted=False)

    assert len(data) == 16 + 2 * SIDE_SIZE
    assert hashlib.sha256(data).hexdigest() == REFERENCE_BLANK_128_SHA256


def test_a_headerless_blank_omits_the_header() -> None:
    data = blank_image(sides=1, headered=False, formatted=False)

    assert len(data) == SIDE_SIZE
    assert data == bytes(SIDE_SIZE)


def test_a_formatted_blank_carries_a_disk_info_block_per_side() -> None:
    data = blank_image(sides=2, headered=False, formatted=True)

    disk, findings = decode(data)

    assert disk.side_count == 2
    assert all(side.is_formatted for side in disk.sides)
    assert [finding.code for finding in findings] == []


def test_a_formatted_blank_declares_no_files() -> None:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True))

    assert disk.sides[0].declared_file_count == 0
    assert disk.sides[0].file_count == 0


def test_a_formatted_blank_numbers_its_sides() -> None:
    disk, _ = decode(blank_image(sides=2, headered=False, formatted=True))

    sides = [DiskInfo.parse(side.blocks[0].payload) for side in disk.sides]

    assert [info.side for info in sides] == [0, 1]
    assert [info.disk_number for info in sides] == [0, 0]


def test_a_formatted_blank_carries_no_date_so_it_is_reproducible() -> None:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True))
    info = DiskInfo.parse(disk.sides[0].blocks[0].payload)

    assert info.raw("manufacturing_date") == bytes(3)
    assert info.raw("rewritten_date") == b"\xff\xff\xff"
    assert info.rewrite_count == 0


def test_a_formatted_blank_is_verified_by_the_bios_string() -> None:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True))

    assert DiskInfo.parse(disk.sides[0].blocks[0].payload).is_verified


def test_two_builds_of_the_same_blank_are_identical() -> None:
    assert blank_image(sides=2, headered=True, formatted=True) == blank_image(
        sides=2, headered=True, formatted=True
    )


def test_a_blank_can_carry_a_game_name() -> None:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="ABC"))

    assert DiskInfo.parse(disk.sides[0].blocks[0].payload).game_name == "ABC"


def test_a_game_name_longer_than_three_characters_is_rejected() -> None:
    with pytest.raises(ValueError, match="three characters"):
        blank_image(sides=1, headered=False, formatted=True, game_name="TOOLONG")


def test_a_side_count_outside_the_supported_range_is_rejected() -> None:
    with pytest.raises(ValueError, match="1 or 2 sides, got 0"):
        blank_image(sides=0, headered=False, formatted=False)

    with pytest.raises(ValueError, match="1 or 2 sides, got 3"):
        blank_image(sides=3, headered=False, formatted=False)


def test_a_formatted_blank_carries_the_values_a_factory_disk_carries() -> None:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True))
    info = disk.sides[0].disk_info

    assert info is not None
    assert info.raw("country") == bytes([0x49])
    assert info.raw("unknown_23") == bytes([0x61])
    assert info.raw("unknown_25") == bytes([0x00, 0x02])
    assert info.raw("writer_serial") == b"\xff\xff"
    assert info.raw("rewritten_date") == b"\xff\xff\xff"


def test_a_formatted_blank_reads_as_a_factory_disk() -> None:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True))

    report = provenance_of(disk)

    assert report.sides[0].origin is Origin.FACTORY
    assert report.sides[0].notes == ()
