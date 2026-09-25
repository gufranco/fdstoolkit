from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.raw import block_regions, encode_block_stream, pack_raw03, unpack_raw03
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Side
from fdstoolkit.drive import vote
from fdstoolkit.drive.align import good_block
from fdstoolkit.drive.vote import MIN_VOTERS, vote_side
from fdstoolkit.edit.files import FileSpec, insert_file

if TYPE_CHECKING:
    import pytest

FILES = 2
DAMAGED = 3
SKIP_SYNC = 40
TRAILING_GAP = 4000


def reference_side() -> Side:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="VOT"))
    for number in range(FILES):
        disk = insert_file(
            disk,
            side=0,
            spec=FileSpec(
                name=f"FILE{number:04d}",
                address=0x6000,
                kind=FileKind.PROGRAM,
                data=hashlib.sha256(f"file {number}".encode()).digest() * 8,
            ),
        )
    return disk.sides[0]


def damaged(side: Side, block: int, offsets: tuple[int, ...]) -> bytes:
    values = bytearray(unpack_raw03(encode_block_stream([b.payload for b in side.blocks])))
    start, _ = block_regions(bytes(values))[block]
    for offset in offsets:
        position = start + SKIP_SYNC + offset
        values[position] = 1 if values[position] == 0 else 0
    return pack_raw03(bytes(values))


def test_three_reads_each_wrong_in_a_different_place_are_voted_back() -> None:
    side = reference_side()
    reads = [damaged(side, DAMAGED, (offset,)) for offset in (10, 90, 170)]

    result = vote_side(reads)

    assert DAMAGED in result.recovered
    assert result.unresolved == ()
    assert [block.payload for block in result.side.blocks] == [b.payload for b in side.blocks]
    assert all(good_block(block) for block in result.side.blocks)


def test_a_block_one_read_got_right_is_taken_from_that_read() -> None:
    side = reference_side()
    clean = pack_raw03(unpack_raw03(encode_block_stream([b.payload for b in side.blocks])))
    reads = [damaged(side, DAMAGED, (10,)), clean]

    result = vote_side(reads)

    assert result.recovered == ()
    assert result.unresolved == ()
    assert [block.payload for block in result.side.blocks] == [b.payload for b in side.blocks]


def test_two_reads_that_both_fail_a_block_are_not_enough_to_vote() -> None:
    side = reference_side()
    reads = [damaged(side, DAMAGED, (10,)), damaged(side, DAMAGED, (90,))]

    result = vote_side(reads)

    assert DAMAGED in result.unresolved
    assert f"a vote needs {MIN_VOTERS}" in result.notes[0]


def test_damage_every_read_shares_is_not_voted_away() -> None:
    side = reference_side()
    reads = [damaged(side, DAMAGED, (10,)) for _ in range(MIN_VOTERS)]

    result = vote_side(reads)

    assert DAMAGED in result.unresolved
    assert result.recovered == ()


def test_reads_with_no_block_in_them_vote_nothing() -> None:
    result = vote_side([pack_raw03(bytes(4000))] * MIN_VOTERS)

    assert result.side.blocks == ()
    assert result.recovered == ()
    assert result.notes == ("no read found a single block on this side",)


def test_a_failed_block_is_copied_from_the_read_that_got_it_right() -> None:
    side = reference_side()
    last = len(side.blocks) - 1
    gap = bytes(TRAILING_GAP)
    stream = unpack_raw03(encode_block_stream([b.payload for b in side.blocks]))
    broken = pack_raw03(unpack_raw03(damaged(side, last, (10,))) + gap)

    result = vote_side([broken, pack_raw03(stream + gap)])

    assert last in result.copied
    assert [block.payload for block in result.side.blocks] == [b.payload for b in side.blocks]


def test_no_captures_at_all_vote_nothing() -> None:
    result = vote_side([])

    assert result.side.blocks == ()
    assert result.notes == ("no read found a single block on this side",)


def test_the_repair_rounds_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vote, "ROUNDS_PER_BLOCK", 0)
    side = reference_side()
    reads = [damaged(side, DAMAGED, (offset,)) for offset in (10, 90, 170)]

    result = vote_side(reads)

    assert DAMAGED in result.unresolved
    assert result.recovered == ()


def test_a_pulse_only_one_read_reaches_is_not_voted_into_the_block() -> None:
    assert vote.majority([b"\x00\x01", b"\x00\x01", b"\x00\x01\x02\x02"]) == b"\x00\x01"
