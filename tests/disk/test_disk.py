from __future__ import annotations

import pytest

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import (
    SIDES_PER_DISK,
    Disk,
    Side,
    TooManySidesError,
    require_readable_sides,
)


def disk_info_block() -> Block:
    payload = bytearray(56)
    payload[0] = 0x01
    payload[1:15] = b"*NINTENDO-HVC*"
    payload[0x10:0x13] = b"SMB"
    return Block(kind=BlockKind.DISK_INFO, payload=bytes(payload))


def file_amount_block(count: int) -> Block:
    return Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([0x02, count]))


def file_header_block(number: int, size: int) -> Block:
    payload = (
        bytes([0x03, number, number])
        + b"FILE    "
        + (0x6000).to_bytes(2, "little")
        + size.to_bytes(2, "little")
        + bytes([0x00])
    )
    return Block(kind=BlockKind.FILE_HEADER, payload=payload)


def file_data_block(size: int) -> Block:
    return Block(kind=BlockKind.FILE_DATA, payload=bytes([0x04]) + bytes(size))


def formatted_side(*, declared: int = 1, files: int = 1, tail: bytes = b"") -> Side:
    blocks: list[Block] = [disk_info_block(), file_amount_block(declared)]
    for index in range(files):
        blocks.append(file_header_block(index, 4))
        blocks.append(file_data_block(4))
    return Side(blocks=tuple(blocks), tail=tail, capacity=65500)


def test_an_empty_side_is_not_formatted() -> None:
    # Arrange
    blocks = ()
    tail = bytes(65500)
    capacity = 65500

    # Act
    side = Side(blocks=blocks, tail=tail, capacity=capacity)

    # Assert
    assert not side.is_formatted
    assert side.disk_info is None


def test_a_formatted_side_exposes_its_disk_info() -> None:
    # Arrange
    side = formatted_side()

    # Act
    info = side.disk_info

    # Assert
    assert side.is_formatted
    assert info is not None
    assert info.game_name == "SMB"


def test_a_side_reports_its_declared_and_actual_file_counts() -> None:
    # Arrange
    declared = 1
    files = 3

    # Act
    side = formatted_side(declared=declared, files=files)

    # Assert
    assert side.declared_file_count == 1
    assert side.file_count == 3
    assert side.hidden_file_count == 2


def test_a_side_without_a_file_amount_block_declares_nothing() -> None:
    # Arrange
    blocks = (disk_info_block(),)
    tail = b""
    capacity = 65500

    # Act
    side = Side(blocks=blocks, tail=tail, capacity=capacity)

    # Assert
    assert side.declared_file_count is None
    assert side.hidden_file_count == 0


def test_a_side_reports_its_content_size() -> None:
    # Arrange
    files = 1

    # Act
    side = formatted_side(files=files)

    # Assert
    assert side.content_size == 56 + 2 + 16 + 5


def test_a_side_knows_whether_its_tail_holds_data() -> None:
    # Arrange
    tails = (bytes(10), bytes([0x00, 0xAB]))

    # Act
    held = [formatted_side(tail=tail).has_data_after_last_block for tail in tails]

    # Assert
    assert held == [False, True]


def test_a_side_lists_file_headers_in_order() -> None:
    # Arrange
    declared = 2
    files = 2

    # Act
    side = formatted_side(declared=declared, files=files)

    # Assert
    assert [header.number for header in side.file_headers] == [0, 1]


def test_a_disk_reports_its_side_count() -> None:
    # Arrange
    sides = (formatted_side(), formatted_side())

    # Act
    disk = Disk(sides=sides)

    # Assert
    assert disk.side_count == 2


def test_a_disk_of_more_than_two_sides_is_refused_for_the_physical_reason() -> None:
    # Arrange
    sides = (formatted_side(), formatted_side(), formatted_side())

    # Act
    with pytest.raises(TooManySidesError) as refused:
        Disk(sides=sides)

    # Assert
    assert refused.type is TooManySidesError
    assert str(refused.value) == (
        "this image holds 3 sides, but a disk physically has 2, so no disk can carry it, "
        "even though the file format allows more. fdstoolkit reads one disk per image"
    )


def test_a_disk_rejects_a_header_count_that_contradicts_its_sides() -> None:
    # Arrange
    sides = (formatted_side(),)
    header_side_count = 3

    # Act
    with pytest.raises(ValueError, match="header declares 3 sides") as raised:
        Disk(sides=sides, header_side_count=header_side_count)

    # Assert
    assert raised.type is ValueError


def test_a_disk_accepts_a_matching_header_count() -> None:
    # Arrange
    sides = (formatted_side(),)
    header_side_count = 1

    # Act
    disk = Disk(sides=sides, header_side_count=header_side_count)

    # Assert
    assert disk.header_side_count == 1


def test_a_side_count_a_card_cannot_have_is_refused() -> None:
    # Arrange
    sides = SIDES_PER_DISK + 1

    # Act
    with pytest.raises(ValueError, match="2 faces") as raised:
        require_readable_sides(sides)

    # Assert
    assert raised.type is ValueError


def test_a_side_count_of_nothing_is_refused() -> None:
    # Arrange
    sides = 0

    # Act
    with pytest.raises(ValueError, match="2 faces") as raised:
        require_readable_sides(sides)

    # Assert
    assert raised.type is ValueError


def test_both_faces_of_one_card_are_allowed() -> None:
    # Arrange
    counts = range(1, SIDES_PER_DISK + 1)

    # Act
    checked = [require_readable_sides(sides) for sides in counts]

    # Assert
    assert checked == [None] * SIDES_PER_DISK
