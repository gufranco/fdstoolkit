from __future__ import annotations

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.crc import block_crc
from fdstoolkit.drive.align import align_blocks, good_block


def block(kind: BlockKind, body: bytes, *, good: bool = True) -> Block:
    payload = bytes([kind]) + body
    stored = block_crc(payload) if good else block_crc(payload) ^ 0xFFFF
    return Block(kind=kind, payload=payload, stored_crc=stored)


def test_a_block_is_good_when_its_checksum_holds() -> None:
    # Arrange
    blocks = (
        block(BlockKind.FILE_AMOUNT, b"\x01"),
        block(BlockKind.FILE_AMOUNT, b"\x01", good=False),
    )

    # Act
    verdicts = [good_block(entry) for entry in blocks]

    # Assert
    assert verdicts == [True, False]


def test_identical_blocks_line_up_one_for_one() -> None:
    # Arrange
    expected = [(True, 0), (True, 1)]

    # Act
    wanted = [block(BlockKind.FILE_AMOUNT, b"\x01"), block(BlockKind.FILE_DATA, b"a")]

    # Assert
    assert align_blocks(wanted, wanted) == expected


def test_a_missing_block_does_not_shift_the_ones_after_it() -> None:
    # Arrange
    first = block(BlockKind.FILE_AMOUNT, b"\x01")
    second = block(BlockKind.FILE_DATA, b"x")

    # Act
    third = block(BlockKind.FILE_DATA, b"y")

    # Assert
    assert align_blocks([first, second, third], [first, third]) == [
        (True, 0),
        (False, None),
        (True, 1),
    ]


def test_a_failed_read_of_the_same_kind_stands_in_for_the_block() -> None:
    # Arrange
    wanted = [block(BlockKind.FILE_DATA, b"right")]

    # Act
    found = [block(BlockKind.FILE_DATA, b"wrong", good=False)]

    # Assert
    assert align_blocks(wanted, found) == [(False, 0)]


def test_a_good_block_of_the_same_kind_with_other_content_does_not() -> None:
    # Arrange
    wanted = [block(BlockKind.FILE_DATA, b"right")]

    # Act
    found = [block(BlockKind.FILE_DATA, b"other")]

    # Assert
    assert align_blocks(wanted, found) == [(False, None)]
