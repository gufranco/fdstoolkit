from __future__ import annotations

import hashlib

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.raw import block_regions, encode_block_stream, pack_raw03, unpack_raw03
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Side
from fdstoolkit.drive.captures import Bundle, Capture
from fdstoolkit.drive.weak import bundle_weak_blocks, weak_blocks
from fdstoolkit.edit.files import FileSpec, insert_file

DATA_BLOCK = 3
INVALID = 3


def reference_side() -> Side:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="WEK"))
    disk = insert_file(
        disk,
        side=0,
        spec=FileSpec(
            name="FILE0000",
            address=0x6000,
            kind=FileKind.PROGRAM,
            data=hashlib.sha256(b"weak").digest() * 8,
        ),
    )
    return disk.sides[0]


def clean_values(side: Side) -> bytearray:
    return bytearray(unpack_raw03(encode_block_stream([b.payload for b in side.blocks])))


def with_invalid_pulse(side: Side, block: int) -> bytes:
    values = clean_values(side)
    _, end = block_regions(bytes(values))[block]
    values[end - 1] = INVALID
    return pack_raw03(bytes(values))


def test_reads_that_agree_everywhere_show_no_weak_block() -> None:
    side = reference_side()
    clean = pack_raw03(bytes(clean_values(side)))

    assert weak_blocks([clean, clean, clean]) == ()


def test_an_invalid_pulse_in_one_read_marks_its_block_weak() -> None:
    side = reference_side()
    clean = pack_raw03(bytes(clean_values(side)))

    found = weak_blocks([clean, with_invalid_pulse(side, DATA_BLOCK), clean])

    assert [entry.block for entry in found] == [DATA_BLOCK]
    assert found[0].invalid == 1
    assert found[0].unstable == 1
    assert found[0].reads == 3
    assert found[0].kind == "file data"


def test_a_block_some_reads_could_not_find_is_listed_first() -> None:
    side = reference_side()
    once = with_invalid_pulse(side, 1)
    values = bytearray(unpack_raw03(with_invalid_pulse(side, DATA_BLOCK)))
    start, _ = block_regions(bytes(values))[DATA_BLOCK]
    values[start + 50] = INVALID
    twice = pack_raw03(bytes(values))

    found = weak_blocks([once, twice])

    assert [entry.block for entry in found] == [DATA_BLOCK, 1]
    assert found[0].missing == 1
    assert "missing from 1 read(s)" in found[0].render()
    assert "missing" not in found[1].render()


def test_no_read_means_no_weak_block() -> None:
    assert weak_blocks([]) == ()
    assert weak_blocks([pack_raw03(bytes(4000))]) == ()


def test_a_bundle_is_mapped_side_by_side() -> None:
    side = reference_side()
    clean = pack_raw03(bytes(clean_values(side)))
    bundle = Bundle(
        captures=(
            Capture(side=0, read=1, data=clean),
            Capture(side=0, read=2, data=with_invalid_pulse(side, DATA_BLOCK)),
            Capture(side=1, read=1, data=clean),
            Capture(side=1, read=2, data=clean),
        ),
        image="game.fds",
        created="2026-09-25T12:00:00Z",
    )

    found = bundle_weak_blocks(bundle)

    assert [(side_index, entry.block) for side_index, entry in found] == [(0, DATA_BLOCK)]


def test_a_read_that_runs_past_its_block_counts_only_the_pulse_that_moved() -> None:
    side = reference_side()
    clean = clean_values(side)
    broken = bytearray(clean)
    start, _ = block_regions(bytes(broken))[DATA_BLOCK]
    broken[start + 50] = 1 if broken[start + 50] == 0 else 0
    gap = bytes(4000)
    reads = [pack_raw03(bytes(values) + gap) for values in (clean, broken, clean)]

    found = weak_blocks(reads)

    assert [(entry.block, entry.unstable) for entry in found] == [(DATA_BLOCK, 1)]
