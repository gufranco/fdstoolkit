from __future__ import annotations

import pytest

from fdstk.core.blocks import Block, BlockKind
from fdstk.core.disk import Disk, Side


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
    side = Side(blocks=(), tail=bytes(65500), capacity=65500)

    assert not side.is_formatted
    assert side.disk_info is None


def test_a_formatted_side_exposes_its_disk_info() -> None:
    side = formatted_side()

    assert side.is_formatted
    assert side.disk_info is not None
    assert side.disk_info.game_name == "SMB"


def test_a_side_reports_its_declared_and_actual_file_counts() -> None:
    side = formatted_side(declared=1, files=3)

    assert side.declared_file_count == 1
    assert side.file_count == 3
    assert side.hidden_file_count == 2


def test_a_side_without_a_file_amount_block_declares_nothing() -> None:
    side = Side(blocks=(disk_info_block(),), tail=b"", capacity=65500)

    assert side.declared_file_count is None
    assert side.hidden_file_count == 0


def test_a_side_reports_its_content_size() -> None:
    side = formatted_side(files=1)

    assert side.content_size == 56 + 2 + 16 + 5


def test_a_side_knows_whether_its_tail_holds_data() -> None:
    assert not formatted_side(tail=bytes(10)).has_data_after_last_block
    assert formatted_side(tail=bytes([0x00, 0xAB])).has_data_after_last_block


def test_a_side_lists_file_headers_in_order() -> None:
    side = formatted_side(declared=2, files=2)

    assert [header.number for header in side.file_headers] == [0, 1]


def test_a_disk_reports_its_side_count() -> None:
    disk = Disk(sides=(formatted_side(), formatted_side()))

    assert disk.side_count == 2


def test_a_disk_rejects_a_header_count_that_contradicts_its_sides() -> None:
    with pytest.raises(ValueError, match="header declares 3 sides"):
        Disk(sides=(formatted_side(),), header_side_count=3)


def test_a_disk_accepts_a_matching_header_count() -> None:
    disk = Disk(sides=(formatted_side(),), header_side_count=1)

    assert disk.header_side_count == 1
