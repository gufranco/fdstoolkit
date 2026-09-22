from __future__ import annotations

import pytest

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.quality.reads import Decay, compare_reads


def _disk(payload_tail: bytes = bytes(41)) -> Disk:
    payload = bytes([BlockKind.DISK_INFO]) + b"*NINTENDO-HVC*" + payload_tail
    return Disk(
        sides=(
            Side(
                blocks=(Block(kind=BlockKind.DISK_INFO, payload=payload),),
                tail=b"",
                capacity=65500,
            ),
        )
    )


def _with_first_byte(value: int) -> Disk:
    return _disk(bytes([value]) + bytes(40))


def test_a_single_read_is_refused() -> None:
    with pytest.raises(ValueError, match="at least two reads"):
        compare_reads([_disk()])


def test_reads_of_different_shapes_are_refused() -> None:
    two_sides = Disk(sides=(_disk().sides[0], _disk().sides[0]))

    with pytest.raises(ValueError, match="different shapes"):
        compare_reads([_disk(), two_sides])


def test_identical_reads_are_perfectly_stable() -> None:
    stats = compare_reads([_disk(), _disk(), _disk()])

    assert stats.passes == 3
    assert stats.stability == 1.0
    assert not stats.unstable_blocks
    assert stats.decay is Decay.NONE


def test_a_block_that_differs_in_one_read_is_unstable() -> None:
    stats = compare_reads([_with_first_byte(0xFF), _with_first_byte(0xFF), _with_first_byte(0xFE)])

    assert stats.stability < 1.0
    assert stats.unstable_blocks == ((0, 0),)
    assert stats.blocks[0].variants == 2
    assert stats.blocks[0].modal_share == pytest.approx(2 / 3)


def test_bits_dropping_to_zero_read_as_decay() -> None:
    stats = compare_reads([_with_first_byte(0xFF), _with_first_byte(0xFF), _with_first_byte(0x0F)])

    assert stats.blocks[0].ones_lost == 4
    assert stats.blocks[0].ones_gained == 0
    assert stats.decay is Decay.LOSS


def test_bits_appearing_read_as_gain() -> None:
    stats = compare_reads([_with_first_byte(0x00), _with_first_byte(0x00), _with_first_byte(0xF0)])

    assert stats.blocks[0].ones_gained == 4
    assert stats.blocks[0].ones_lost == 0
    assert stats.decay is Decay.GAIN


def test_flips_in_both_directions_read_as_mixed() -> None:
    stats = compare_reads(
        [
            _with_first_byte(0b1010_1010),
            _with_first_byte(0b1010_1010),
            _with_first_byte(0b0101_0101),
        ]
    )

    assert stats.decay is Decay.MIXED


def test_a_tie_between_two_readings_still_reports_both_variants() -> None:
    stats = compare_reads([_with_first_byte(0x01), _with_first_byte(0x02)])

    assert stats.blocks[0].variants == 2
    assert stats.blocks[0].modal_share == pytest.approx(0.5)


def test_a_block_report_names_where_it_came_from() -> None:
    stats = compare_reads([_disk(), _disk()])

    assert stats.blocks[0].side == 0
    assert stats.blocks[0].block == 0
    assert stats.blocks[0].kind == "disk_info"


def test_the_flip_rate_is_the_complement_of_the_modal_share() -> None:
    stats = compare_reads([_with_first_byte(0xFF), _with_first_byte(0xFF), _with_first_byte(0xFE)])

    assert stats.blocks[0].flip_rate == pytest.approx(1 / 3)
