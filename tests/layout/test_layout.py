from __future__ import annotations

from dataclasses import replace

import pytest

from fdstk.build.blank import blank_image
from fdstk.codecs.fds import decode
from fdstk.core.blocks import Block, BlockKind, FileKind
from fdstk.core.disk import Disk
from fdstk.edit.files import FileSpec, insert_file
from fdstk.quality.layout import BIT_RATE_HZ, layout_of


def sample(*, files: int = 0, size: int = 1024) -> Disk:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    for index in range(files):
        disk = insert_file(
            disk,
            side=0,
            spec=FileSpec(
                name=f"F{index}",
                address=0x6000,
                kind=FileKind.PROGRAM,
                data=bytes([index + 1]) * size,
            ),
        )
    return disk


def with_tail(disk: Disk, tail: bytes) -> Disk:
    side = disk.sides[0]
    return Disk(sides=(replace(side, tail=tail),), header_side_count=disk.header_side_count)


def set_file_amount(disk: Disk, count: int) -> Disk:
    side = disk.sides[0]
    blocks = tuple(
        Block(kind=block.kind, payload=bytes([BlockKind.FILE_AMOUNT, count]))
        if block.kind is BlockKind.FILE_AMOUNT
        else block
        for block in side.blocks
    )
    return Disk(sides=(replace(side, blocks=blocks),), header_side_count=disk.header_side_count)


def test_an_empty_side_places_no_files() -> None:
    report = layout_of(sample())

    assert report.sides[0].placements == ()
    assert report.sides[0].dead_bytes == 0


def test_a_file_is_placed_after_the_lead_in() -> None:
    placement = layout_of(sample(files=1)).sides[0].placements[0]

    assert placement.offset > 0
    assert placement.seconds_to_reach > 0


def test_a_later_file_costs_more_to_reach() -> None:
    placements = layout_of(sample(files=3)).sides[0].placements

    offsets = [entry.offset for entry in placements]
    assert offsets == sorted(offsets)
    assert placements[-1].seconds_to_reach > placements[0].seconds_to_reach


def test_the_time_to_reach_follows_the_documented_bit_rate() -> None:
    placement = layout_of(sample(files=1)).sides[0].placements[0]

    assert placement.seconds_to_reach == pytest.approx(placement.offset * 8 / BIT_RATE_HZ)


def test_trailing_data_counts_as_dead_weight() -> None:
    report = layout_of(with_tail(sample(files=1), b"junk"))

    assert report.sides[0].dead_bytes == 4
    assert report.dead_bytes == 4


def test_a_hidden_file_is_marked_as_one() -> None:
    report = layout_of(set_file_amount(sample(files=2), 1))

    assert [entry.hidden for entry in report.sides[0].placements] == [False, True]


def test_the_stream_length_covers_the_whole_side() -> None:
    side = layout_of(sample(files=2)).sides[0]

    assert side.stream_bytes > side.placements[-1].offset
    assert side.seconds_to_read == pytest.approx(side.stream_bytes * 8 / BIT_RATE_HZ)


def test_an_unformatted_side_reports_no_stream() -> None:
    blank, _ = decode(blank_image(sides=1, headered=False, formatted=False))

    report = layout_of(blank)

    assert report.sides[0].stream_bytes == 0
    assert report.sides[0].placements == ()


def test_every_side_is_reported() -> None:
    disk, _ = decode(blank_image(sides=2, headered=False, formatted=True))

    report = layout_of(disk)

    assert [side.side for side in report.sides] == [0, 1]


def test_a_reorder_saving_is_reported_when_a_small_file_sits_last() -> None:
    disk = insert_file(
        sample(files=1, size=8192),
        side=0,
        spec=FileSpec(name="SMALL", address=0x6000, kind=FileKind.PROGRAM, data=b"\x01" * 16),
    )

    side = layout_of(disk).sides[0]

    assert side.reorder_saving_bytes > 0


def test_a_side_already_ordered_smallest_first_reports_no_saving() -> None:
    disk = insert_file(
        sample(files=1, size=16),
        side=0,
        spec=FileSpec(name="BIG", address=0x6000, kind=FileKind.PROGRAM, data=b"\x01" * 8192),
    )

    assert layout_of(disk).sides[0].reorder_saving_bytes == 0


def test_the_note_names_the_saving_and_calls_it_a_measurement() -> None:
    disk = insert_file(
        sample(files=1, size=8192),
        side=0,
        spec=FileSpec(name="SMALL", address=0x6000, kind=FileKind.PROGRAM, data=b"\x01" * 16),
    )

    side = layout_of(disk).sides[0]

    assert str(side.reorder_saving_bytes) in side.note
    assert "measurement rather than a recommendation" in side.note


def test_a_side_with_one_file_reports_no_saving() -> None:
    assert layout_of(sample(files=1)).sides[0].note == ""


def test_a_header_without_data_contributes_no_data_size() -> None:
    disk = sample(files=1)
    side = disk.sides[0]
    blocks = tuple(block for block in side.blocks if block.kind is not BlockKind.FILE_DATA)
    trimmed = Disk(sides=(replace(side, blocks=blocks),))

    placement = layout_of(trimmed).sides[0].placements[0]

    assert placement.size == 0


def test_a_side_whose_last_file_has_no_data_still_measures_a_saving() -> None:
    disk = sample(files=2)
    side = disk.sides[0]
    blocks = tuple(side.blocks[:-1])
    trimmed = Disk(sides=(replace(side, blocks=blocks),))

    result = layout_of(trimmed).sides[0]

    assert len(result.placements) == 2
    assert result.reorder_saving_bytes >= 0
