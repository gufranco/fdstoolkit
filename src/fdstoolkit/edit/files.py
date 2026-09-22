from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from fdstoolkit.core.blocks import (
    FILE_NAME_SIZE,
    Block,
    BlockKind,
    FileHeader,
    FileKind,
)
from fdstoolkit.core.disk import Disk, Side

FILE_AMOUNT_OFFSET: Final = 1
MAX_FILE_AMOUNT: Final = 0xFF


@dataclass(frozen=True, slots=True)
class ExtractedFile:
    side: int
    position: int
    number: int
    file_id: int
    name: str
    address: int
    kind: FileKind
    data: bytes
    hidden: bool

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass(frozen=True, slots=True)
class FileSpec:
    name: str
    address: int
    kind: FileKind
    data: bytes
    file_id: int | None = None


def _side_of(disk: Disk, side: int) -> Side:
    if not 0 <= side < disk.side_count:
        message = f"the image has no side {side}"
        raise ValueError(message)
    return disk.sides[side]


def _pairs(side: Side) -> list[tuple[int, Block, Block | None]]:
    found: list[tuple[int, Block, Block | None]] = []
    blocks = list(side.blocks)
    for index, block in enumerate(blocks):
        if block.kind is not BlockKind.FILE_HEADER:
            continue
        follower = blocks[index + 1] if index + 1 < len(blocks) else None
        data = follower if follower is not None and follower.kind is BlockKind.FILE_DATA else None
        found.append((index, block, data))
    return found


def declared_file_count(disk: Disk, *, side: int) -> int | None:
    return _side_of(disk, side).declared_file_count


def extract_files(disk: Disk) -> tuple[ExtractedFile, ...]:
    out: list[ExtractedFile] = []
    for side_index, side in enumerate(disk.sides):
        declared = side.declared_file_count or 0
        for position, (_, header_block, data_block) in enumerate(_pairs(side)):
            header = FileHeader.parse(header_block.payload)
            out.append(
                ExtractedFile(
                    side=side_index,
                    position=position,
                    number=header.number,
                    file_id=header.file_id,
                    name=header.name,
                    address=header.address,
                    kind=header.kind,
                    data=data_block.payload[1:] if data_block is not None else b"",
                    hidden=position >= declared,
                )
            )
    return tuple(out)


def _header_block(spec: FileSpec, number: int) -> Block:
    if len(spec.name) > FILE_NAME_SIZE:
        message = f"a file name is at most eight characters, got {len(spec.name)}"
        raise ValueError(message)
    payload = (
        bytes([BlockKind.FILE_HEADER, number, spec.file_id if spec.file_id is not None else number])
        + spec.name.encode("ascii").ljust(FILE_NAME_SIZE, b" ")
        + spec.address.to_bytes(2, "little")
        + len(spec.data).to_bytes(2, "little")
        + bytes([max(int(spec.kind), 0)])
    )
    return Block(kind=BlockKind.FILE_HEADER, payload=payload)


def _replace_side(disk: Disk, index: int, side: Side) -> Disk:
    sides = list(disk.sides)
    sides[index] = side
    return Disk(sides=tuple(sides), header_side_count=disk.header_side_count)


def _with_amount(blocks: list[Block], count: int) -> list[Block]:
    return [
        Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([BlockKind.FILE_AMOUNT, count]))
        if block.kind is BlockKind.FILE_AMOUNT
        else block
        for block in blocks
    ]


def insert_file(disk: Disk, *, side: int, spec: FileSpec) -> Disk:
    target = _side_of(disk, side)
    number = len(_pairs(target))
    header = _header_block(spec, number)
    data = Block(kind=BlockKind.FILE_DATA, payload=bytes([BlockKind.FILE_DATA]) + spec.data)

    blocks = [*target.blocks, header, data]
    declared = (target.declared_file_count or 0) + 1
    if declared > MAX_FILE_AMOUNT:
        message = f"a side holds at most {MAX_FILE_AMOUNT} declared files"
        raise ValueError(message)
    blocks = _with_amount(blocks, declared)

    content = sum(block.size for block in blocks)
    if content > target.capacity:
        message = (
            f"the file does not fit: the side would hold {content} bytes "
            f"against a capacity of {target.capacity}"
        )
        raise ValueError(message)

    return _replace_side(disk, side, Side(blocks=tuple(blocks), tail=b"", capacity=target.capacity))


def remove_file(disk: Disk, *, side: int, position: int) -> Disk:
    target = _side_of(disk, side)
    pairs = _pairs(target)
    if not 0 <= position < len(pairs):
        message = f"there is no file at position {position} on side {side}"
        raise ValueError(message)

    header_index, _, data_block = pairs[position]
    drop = {header_index}
    if data_block is not None:
        drop.add(header_index + 1)

    blocks = [block for index, block in enumerate(target.blocks) if index not in drop]
    declared = max((target.declared_file_count or 1) - 1, 0)
    blocks = _with_amount(blocks, declared)

    return _replace_side(
        disk,
        side,
        Side(blocks=tuple(blocks), tail=target.tail, capacity=target.capacity),
    )


def set_declared_file_count(disk: Disk, *, side: int, count: int) -> Disk:
    target = _side_of(disk, side)
    present = len(_pairs(target))
    if count > present:
        message = f"the side holds only {present} file(s), cannot declare {count}"
        raise ValueError(message)

    return _replace_side(
        disk,
        side,
        Side(
            blocks=tuple(_with_amount(list(target.blocks), count)),
            tail=target.tail,
            capacity=target.capacity,
        ),
    )
