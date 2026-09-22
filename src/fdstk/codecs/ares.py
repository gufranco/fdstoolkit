from __future__ import annotations

from typing import Final

from fdstk.core.blocks import (
    DISK_INFO_SIZE,
    FILE_AMOUNT_SIZE,
    FILE_HEADER_SIZE,
    FILE_SIZE_OFFSET,
    Block,
    BlockKind,
)
from fdstk.core.crc import CRC_SIZE, block_crc, decode_crc
from fdstk.core.disk import Disk, Side

ARES_SIDE_SIZE: Final = 0x12000
PREGAP: Final = 0xE00
BLOCK_GAP: Final = 0x80
SYNC_MARK: Final = 0x80
FDS_SIDE_CAPACITY: Final = 65500
SIDES_PER_DISK: Final = 2

FIXED_LENGTHS: Final[dict[int, int]] = {
    BlockKind.DISK_INFO: DISK_INFO_SIZE,
    BlockKind.FILE_AMOUNT: FILE_AMOUNT_SIZE,
    BlockKind.FILE_HEADER: FILE_HEADER_SIZE,
}

REQUIRED_OPENING: Final = (
    BlockKind.DISK_INFO,
    BlockKind.FILE_AMOUNT,
    BlockKind.FILE_HEADER,
    BlockKind.FILE_DATA,
)


def side_file_names(sides: int) -> tuple[str, ...]:
    return tuple(
        f"disk{1 + index // SIDES_PER_DISK}.side{'AB'[index % SIDES_PER_DISK]}"
        for index in range(sides)
    )


def encode_side(side: Side) -> bytes:
    kinds = tuple(block.kind for block in side.blocks[: len(REQUIRED_OPENING)])
    if kinds != REQUIRED_OPENING:
        message = (
            "ares loads a side only when it is formatted and holds at least one file, "
            "so this side cannot be written for it"
        )
        raise ValueError(message)

    out = bytearray()
    for index, block in enumerate(side.blocks):
        if index >= len(REQUIRED_OPENING) and block.kind not in (
            BlockKind.FILE_HEADER,
            BlockKind.FILE_DATA,
        ):
            break
        out += bytes(PREGAP if index == 0 else BLOCK_GAP)
        out.append(SYNC_MARK)
        out += block.payload
        out += block_crc(block.payload).to_bytes(CRC_SIZE, "little")
    if len(out) > ARES_SIDE_SIZE:
        message = f"the side needs {len(out)} bytes and an ares side holds {ARES_SIDE_SIZE}"
        raise ValueError(message)
    return bytes(out).ljust(ARES_SIDE_SIZE, b"\0")


def split_for_ares(disk: Disk) -> dict[str, bytes]:
    names = side_file_names(disk.side_count)
    return {name: encode_side(side) for name, side in zip(names, disk.sides, strict=True)}


def _length(kind: int, previous: Block | None) -> int | None:
    fixed = FIXED_LENGTHS.get(kind)
    if fixed is not None:
        return fixed
    if kind == BlockKind.FILE_DATA and previous is not None:
        declared = int.from_bytes(
            previous.payload[FILE_SIZE_OFFSET : FILE_SIZE_OFFSET + 2], "little"
        )
        return 1 + declared
    return None


def _next_sync(data: bytes, cursor: int) -> int | None:
    while cursor < len(data) and data[cursor] == 0:
        cursor += 1
    if cursor >= len(data) or data[cursor] != SYNC_MARK:
        return None
    return cursor + 1


def decode_side(data: bytes) -> Side:
    if len(data) != ARES_SIDE_SIZE:
        message = f"an ares side file is {ARES_SIDE_SIZE} bytes, got {len(data)}"
        raise ValueError(message)

    blocks: list[Block] = []
    cursor = 0
    while True:
        start = _next_sync(data, cursor)
        if start is None or start >= len(data):
            break
        kind = data[start]
        previous = blocks[-1] if blocks and blocks[-1].kind is BlockKind.FILE_HEADER else None
        length = _length(kind, previous)
        end = start + length + CRC_SIZE if length is not None else len(data) + 1
        if length is None or end > len(data):
            break
        blocks.append(
            Block(
                kind=BlockKind(kind),
                payload=data[start : start + length],
                stored_crc=decode_crc(data[start + length : end]),
            )
        )
        cursor = end

    return Side(blocks=tuple(blocks), tail=b"", capacity=FDS_SIDE_CAPACITY)
