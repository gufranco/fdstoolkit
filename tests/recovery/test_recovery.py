from __future__ import annotations

import hashlib

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.raw import block_regions, encode_block_stream, pack_raw03, unpack_raw03
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Side
from fdstoolkit.drive.captures import Bundle, Capture
from fdstoolkit.drive.recovery import rebuild, recover
from fdstoolkit.edit.files import FileSpec, insert_file
from fdstoolkit.hardware.ports import BlockRead
from fdstoolkit.hardware.session import DumpResult, Grade, SideDump

DAMAGED = 3
TRAILING_GAP = 4000


def reference_side() -> Side:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="REC"))
    disk = insert_file(
        disk,
        side=0,
        spec=FileSpec(
            name="FILE0000",
            address=0x6000,
            kind=FileKind.PROGRAM,
            data=hashlib.sha256(b"recover").digest() * 8,
        ),
    )
    return disk.sides[0]


def damaged(side: Side, offset: int) -> bytes:
    values = bytearray(unpack_raw03(encode_block_stream([b.payload for b in side.blocks])))
    start, _ = block_regions(bytes(values))[DAMAGED]
    values[start + 40 + offset] = 1 if values[start + 40 + offset] == 0 else 0
    return pack_raw03(bytes(values) + bytes(TRAILING_GAP))


def dumped(side: Side) -> DumpResult:
    reads = tuple(
        BlockRead(
            index=index,
            payload=block.payload if index != DAMAGED else block.payload[:-1] + b"\x00",
            crc_ok=index != DAMAGED,
            attempts=1,
        )
        for index, block in enumerate(side.blocks)
    )
    return DumpResult(sides=(SideDump(index=0, blocks=reads),))


def test_a_block_every_read_failed_is_recovered_by_the_vote() -> None:
    side = reference_side()
    captures = [
        Capture(side=0, read=number, data=damaged(side, offset))
        for number, offset in enumerate((10, 90, 170), start=1)
    ]

    outcome = recover(dumped(side), captures)

    block = outcome.result.sides[0].blocks[DAMAGED]
    assert block.crc_ok
    assert block.payload == side.blocks[DAMAGED].payload
    assert block.attempts == len(captures)
    assert outcome.recovered == ((0, DAMAGED),)
    assert outcome.result.grade is Grade.MARGINAL
    assert outcome.lines == (f"  side 0 block {DAMAGED}: recovered by a pulse vote across 3 reads",)


def test_too_few_reads_leave_the_block_failed_and_say_why() -> None:
    side = reference_side()
    captures = [Capture(side=0, read=1, data=damaged(side, 10))]

    outcome = recover(dumped(side), captures)

    assert not outcome.result.sides[0].blocks[DAMAGED].crc_ok
    assert outcome.recovered == ()
    assert "a vote needs 3" in outcome.lines[0]


def test_a_dump_that_read_clean_is_left_alone() -> None:
    side = reference_side()
    clean = DumpResult(
        sides=(
            SideDump(
                index=0,
                blocks=tuple(
                    BlockRead(index=index, payload=block.payload, crc_ok=True, attempts=1)
                    for index, block in enumerate(side.blocks)
                ),
            ),
        )
    )

    outcome = recover(clean, [])

    assert outcome.result == clean
    assert outcome.lines == ()


def test_a_bundle_is_rebuilt_into_a_disk_side_by_side() -> None:
    side = reference_side()
    bundle = Bundle(
        captures=tuple(
            Capture(side=0, read=number, data=damaged(side, offset))
            for number, offset in enumerate((10, 90, 170), start=1)
        ),
        image="game.fds",
        created="2026-09-25T12:00:00Z",
    )

    rebuilt = rebuild(bundle)

    assert [block.payload for block in rebuilt.disk.sides[0].blocks] == [
        block.payload for block in side.blocks
    ]
    assert rebuilt.unresolved == ()
    assert rebuilt.lines == ("  side 0: 1 block(s) recovered by a pulse vote",)


def test_a_bundle_with_a_block_no_vote_can_fix_says_which() -> None:
    side = reference_side()
    bundle = Bundle(
        captures=(Capture(side=0, read=1, data=damaged(side, 10)),),
        image="game.fds",
        created="2026-09-25T12:00:00Z",
    )

    rebuilt = rebuild(bundle)

    assert rebuilt.unresolved == ((0, DAMAGED),)
    assert any("never read clean" in line for line in rebuilt.lines)


def test_a_failed_block_with_no_saved_reads_stays_failed_and_says_so() -> None:
    side = reference_side()

    outcome = recover(dumped(side), [])

    assert not outcome.result.sides[0].blocks[DAMAGED].crc_ok
    assert outcome.recovered == ()
    assert outcome.lines == ("  side 0 no read found a single block on this side",)
