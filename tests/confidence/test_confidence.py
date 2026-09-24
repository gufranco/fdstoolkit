from __future__ import annotations

import pytest

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.quality.confidence import (
    LOW_CONFIDENCE,
    Basis,
    score_disk,
)
from fdstoolkit.quality.reads import compare_reads

PAYLOAD = bytes([BlockKind.DISK_INFO]) + b"*NINTENDO-HVC*" + bytes(41)


def _disk(*, crc: str = "valid", tail: bytes = bytes(41)) -> Disk:
    payload = bytes([BlockKind.DISK_INFO]) + b"*NINTENDO-HVC*" + tail
    block = Block(kind=BlockKind.DISK_INFO, payload=payload)
    if crc == "valid":
        block = block.with_computed_crc()
    elif crc == "null":
        block = block.with_null_crc()
    elif crc == "mismatch":
        block = Block(kind=BlockKind.DISK_INFO, payload=payload, stored_crc=0x1234)
    return Disk(sides=(Side(blocks=(block,), tail=b"", capacity=65500),))


def test_a_valid_crc_carries_most_of_the_confidence() -> None:
    report = score_disk(_disk())

    assert report.blocks[0].confidence >= 0.9
    assert Basis.CRC_VALID in report.blocks[0].basis


def test_a_mismatched_crc_destroys_the_confidence() -> None:
    report = score_disk(_disk(crc="mismatch"))

    assert report.blocks[0].confidence < LOW_CONFIDENCE
    assert Basis.CRC_MISMATCH in report.blocks[0].basis


def test_a_null_crc_leaves_the_block_unproven() -> None:
    report = score_disk(_disk(crc="null"))

    assert 0.3 < report.blocks[0].confidence < 0.9
    assert Basis.CRC_NULL in report.blocks[0].basis


def test_a_stripped_crc_leaves_the_block_unproven() -> None:
    report = score_disk(_disk(crc="absent"))

    assert Basis.CRC_ABSENT in report.blocks[0].basis


def test_agreeing_reads_raise_the_confidence_above_a_single_read() -> None:
    alone = score_disk(_disk())
    stats = compare_reads([_disk(), _disk(), _disk(), _disk(), _disk()])

    together = score_disk(_disk(), reads=stats)

    assert together.blocks[0].confidence > alone.blocks[0].confidence
    assert Basis.READS_AGREE in together.blocks[0].basis


def test_disagreeing_reads_lower_the_confidence() -> None:
    stats = compare_reads([_disk(), _disk(), _disk(tail=bytes([1]) + bytes(40))])

    report = score_disk(_disk(), reads=stats)

    assert report.blocks[0].confidence < 0.9
    assert Basis.READS_DISAGREE in report.blocks[0].basis


def test_a_single_read_is_named_in_the_basis() -> None:
    report = score_disk(_disk())

    assert Basis.SINGLE_READ in report.blocks[0].basis


def test_a_report_summarises_its_worst_and_mean_confidence() -> None:
    report = score_disk(_disk())

    assert report.worst == pytest.approx(report.mean)
    assert not report.low_confidence_blocks


def test_a_mismatched_block_is_listed_as_low_confidence() -> None:
    report = score_disk(_disk(crc="mismatch"))

    assert report.low_confidence_blocks == ((0, 0),)


def test_an_empty_disk_scores_nothing_and_stays_safe() -> None:
    empty = Disk(sides=(Side(blocks=(), tail=b"", capacity=65500),))

    report = score_disk(empty)

    assert report.blocks == ()
    assert report.worst == 0.0
    assert report.mean == 0.0


def test_read_statistics_of_a_different_shape_are_refused() -> None:
    other = Disk(
        sides=(
            Side(
                blocks=(
                    Block(kind=BlockKind.DISK_INFO, payload=PAYLOAD),
                    Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([2, 1])),
                ),
                tail=b"",
                capacity=65500,
            ),
        )
    )
    stats = compare_reads([other, other])

    with pytest.raises(ValueError, match="do not describe this image"):
        score_disk(_disk(), reads=stats)
