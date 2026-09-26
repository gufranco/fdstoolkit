from __future__ import annotations

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.crc import block_crc
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.edit.files import FileSpec, insert_file
from fdstoolkit.quality.consensus import BlockVerdict, build_consensus, compare_images


def sample() -> Disk:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    return disk


def altered(fill: int) -> Disk:
    original = sample().sides[0]
    blocks = list(original.blocks)
    blocks[1] = Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([0x02, fill]))
    return Disk(sides=(Side(blocks=tuple(blocks), tail=b"", capacity=original.capacity),))


def test_identical_dumps_agree_on_every_block() -> None:
    result = build_consensus([sample(), sample(), sample()])

    assert result.disagreements == ()
    assert all(verdict is BlockVerdict.AGREED for verdict in result.verdicts)


def test_a_majority_decides_a_disagreeing_block() -> None:
    result = build_consensus([sample(), sample(), altered(9)])

    assert result.disagreements == ((0, 1),)
    assert result.verdicts[1] is BlockVerdict.MAJORITY
    assert result.disk.sides[0].blocks[1].payload == sample().sides[0].blocks[1].payload


def test_a_tie_is_reported_rather_than_guessed() -> None:
    result = build_consensus([sample(), altered(9)])

    assert result.verdicts[1] is BlockVerdict.TIED
    assert result.disagreements == ((0, 1),)


def test_a_consensus_needs_at_least_two_dumps() -> None:
    with pytest.raises(ValueError, match="at least two"):
        build_consensus([sample()])


def test_dumps_of_different_shapes_are_refused() -> None:
    one = sample()
    other = Disk(sides=(one.sides[0], one.sides[0]))

    with pytest.raises(ValueError, match="different numbers of sides"):
        build_consensus([one, other])


def test_the_consensus_carries_the_agreed_bytes() -> None:
    result = build_consensus([altered(9), altered(9), sample()])

    assert result.disk.sides[0].blocks[1].payload == bytes([0x02, 9])


def test_comparing_two_images_names_the_first_difference() -> None:
    report = compare_images(sample(), altered(9))

    assert report.identical is False
    assert report.differing_blocks == ((0, 1),)


def test_comparing_identical_images_says_so() -> None:
    report = compare_images(sample(), sample())

    assert report.identical
    assert report.differing_blocks == ()


def test_comparing_reports_a_side_count_mismatch() -> None:
    one = sample()
    two = Disk(sides=(one.sides[0], one.sides[0]))

    report = compare_images(one, two)

    assert not report.identical
    assert "side count" in report.summary


def test_comparing_reports_a_block_count_mismatch() -> None:
    original = sample().sides[0]
    shorter = Disk(sides=(Side(blocks=original.blocks[:1], tail=b"", capacity=original.capacity),))

    report = compare_images(sample(), shorter)

    assert not report.identical
    assert "block count" in report.summary


def test_the_stability_map_covers_every_block() -> None:
    disks = [sample(), sample()]

    result = build_consensus(disks)

    assert len(result.stability) == sum(len(side.blocks) for side in disks[0].sides)
    assert all(entry.stable for entry in result.stability)
    assert result.stable


def test_the_stability_map_reports_the_agreement_of_a_disputed_block() -> None:
    disks = [sample(), sample(), altered(0x05)]

    result = build_consensus(disks)

    disputed = next(entry for entry in result.stability if not entry.stable)
    assert disputed.variants == 2
    assert disputed.agreement == pytest.approx(2 / 3)
    assert disputed.kind == "file_amount"
    assert not result.stable


def with_files(count: int) -> Disk:
    disk = sample()
    for number in range(count):
        disk = insert_file(
            disk,
            side=0,
            spec=FileSpec(
                name=f"FILE{number}",
                address=0x6000,
                kind=FileKind.PROGRAM,
                data=bytes([number + 1]) * 32,
            ),
        )
    return disk


def without_last_file(disk: Disk) -> Disk:
    side = disk.sides[0]
    return Disk(sides=(Side(blocks=side.blocks[:-2], tail=b"", capacity=side.capacity),))


def test_a_dump_that_lost_its_last_file_still_joins_the_merge() -> None:
    full = with_files(3)

    result = build_consensus([full, without_last_file(full), full])

    assert result.disk.sides[0].blocks == full.sides[0].blocks
    assert result.disagreements == ()
    assert [entry.missing for entry in result.stability][-2:] == [1, 1]


def with_block(disk: Disk, index: int, payload: bytes, stored: int) -> Disk:
    side = disk.sides[0]
    blocks = list(side.blocks)
    blocks[index] = Block(kind=blocks[index].kind, payload=payload, stored_crc=stored)
    return Disk(sides=(Side(blocks=tuple(blocks), tail=b"", capacity=side.capacity),))


def test_the_copy_whose_checksum_passes_beats_a_majority_that_fails() -> None:
    full = with_files(1)
    good = full.sides[0].blocks[3].payload
    bad = good[:-1] + bytes([good[-1] ^ 0xFF])
    right = with_block(full, 3, good, block_crc(good))
    wrong = with_block(full, 3, bad, block_crc(good))

    result = build_consensus([wrong, wrong, right])

    assert result.disk.sides[0].blocks[3].payload == good
    assert result.verdicts[3] is BlockVerdict.CHECKSUM
