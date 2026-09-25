from __future__ import annotations

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.crc import block_crc
from fdstoolkit.drive.align import align_blocks, good_block


def block(kind: BlockKind, body: bytes, *, good: bool = True) -> Block:
    payload = bytes([kind]) + body
    stored = block_crc(payload) if good else block_crc(payload) ^ 0xFFFF
    return Block(kind=kind, payload=payload, stored_crc=stored)


def test_a_block_is_good_when_its_checksum_holds() -> None:
    assert good_block(block(BlockKind.FILE_AMOUNT, b"\x01"))
    assert not good_block(block(BlockKind.FILE_AMOUNT, b"\x01", good=False))


def test_identical_blocks_line_up_one_for_one() -> None:
    wanted = [block(BlockKind.FILE_AMOUNT, b"\x01"), block(BlockKind.FILE_DATA, b"a")]

    assert align_blocks(wanted, wanted) == [(True, 0), (True, 1)]


def test_a_missing_block_does_not_shift_the_ones_after_it() -> None:
    first = block(BlockKind.FILE_AMOUNT, b"\x01")
    second = block(BlockKind.FILE_DATA, b"x")
    third = block(BlockKind.FILE_DATA, b"y")

    assert align_blocks([first, second, third], [first, third]) == [
        (True, 0),
        (False, None),
        (True, 1),
    ]


def test_a_failed_read_of_the_same_kind_stands_in_for_the_block() -> None:
    wanted = [block(BlockKind.FILE_DATA, b"right")]
    found = [block(BlockKind.FILE_DATA, b"wrong", good=False)]

    assert align_blocks(wanted, found) == [(False, 0)]


def test_a_good_block_of_the_same_kind_with_other_content_does_not() -> None:
    wanted = [block(BlockKind.FILE_DATA, b"right")]
    found = [block(BlockKind.FILE_DATA, b"other")]

    assert align_blocks(wanted, found) == [(False, None)]
