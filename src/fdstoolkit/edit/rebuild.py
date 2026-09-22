from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from fdstoolkit.core.blocks import (
    FILE_SIZE_OFFSET,
    Block,
    BlockKind,
    CrcStatus,
    FileHeader,
)
from fdstoolkit.core.disk import Disk, Side

FILE_NUMBER_OFFSET: Final = 1
MAX_FILE_AMOUNT: Final = 0xFF


@dataclass(frozen=True, slots=True)
class RebuildOptions:
    keep_tail: bool = False
    reveal_hidden: bool = False
    drop_hidden: bool = False
    renumber: bool = False


@dataclass(frozen=True, slots=True)
class RebuildAction:
    side: int
    kind: str
    detail: str


@dataclass(frozen=True, slots=True)
class RebuildReport:
    actions: tuple[RebuildAction, ...] = field(default=())

    @property
    def changed(self) -> bool:
        return bool(self.actions)


def _pairs(blocks: list[Block]) -> list[tuple[int, int | None]]:
    found: list[tuple[int, int | None]] = []
    for index, block in enumerate(blocks):
        if block.kind is not BlockKind.FILE_HEADER:
            continue
        follows = index + 1 < len(blocks) and blocks[index + 1].kind is BlockKind.FILE_DATA
        found.append((index, index + 1 if follows else None))
    return found


def _patched(block: Block, payload: bytes) -> Block:
    return Block(kind=block.kind, payload=payload, stored_crc=block.stored_crc)


def _fix_sizes(blocks: list[Block], side: int, actions: list[RebuildAction]) -> list[Block]:
    out = list(blocks)
    for header_index, data_index in _pairs(out):
        if data_index is None:
            continue
        header = FileHeader.parse(out[header_index].payload)
        actual = out[data_index].size - 1
        if header.size == actual:
            continue
        payload = bytearray(out[header_index].payload)
        payload[FILE_SIZE_OFFSET : FILE_SIZE_OFFSET + 2] = actual.to_bytes(2, "little")
        out[header_index] = _patched(out[header_index], bytes(payload))
        actions.append(
            RebuildAction(
                side=side,
                kind="file_size",
                detail=f"{header.name or 'file'} declared {header.size} bytes, holds {actual}",
            )
        )
    return out


def _renumber(blocks: list[Block], side: int, actions: list[RebuildAction]) -> list[Block]:
    out = list(blocks)
    changed = 0
    for position, (header_index, _) in enumerate(_pairs(out)):
        payload = bytearray(out[header_index].payload)
        if payload[FILE_NUMBER_OFFSET] == position:
            continue
        payload[FILE_NUMBER_OFFSET] = position
        out[header_index] = _patched(out[header_index], bytes(payload))
        changed += 1
    if changed:
        actions.append(
            RebuildAction(side=side, kind="renumber", detail=f"{changed} file number(s) reordered")
        )
    return out


def _drop_hidden(
    blocks: list[Block], side: int, declared: int, actions: list[RebuildAction]
) -> list[Block]:
    pairs = _pairs(blocks)
    if len(pairs) <= declared:
        return blocks
    keep = set(range(len(blocks)))
    for header_index, data_index in pairs[declared:]:
        keep.discard(header_index)
        if data_index is not None:
            keep.discard(data_index)
    actions.append(
        RebuildAction(
            side=side,
            kind="drop_hidden",
            detail=f"{len(pairs) - declared} hidden file(s) removed",
        )
    )
    return [block for index, block in enumerate(blocks) if index in keep]


def _reveal(
    blocks: list[Block], side: int, declared: int, actions: list[RebuildAction]
) -> list[Block]:
    actual = len(_pairs(blocks))
    if actual <= declared:
        return blocks
    out = list(blocks)
    for index, block in enumerate(out):
        if block.kind is not BlockKind.FILE_AMOUNT:
            continue
        payload = bytes([BlockKind.FILE_AMOUNT, min(actual, MAX_FILE_AMOUNT)])
        out[index] = _patched(block, payload)
    actions.append(
        RebuildAction(
            side=side,
            kind="reveal",
            detail=f"file count raised from {declared} to {actual}",
        )
    )
    return out


def _fix_crcs(blocks: list[Block], side: int, actions: list[RebuildAction]) -> list[Block]:
    out = list(blocks)
    repaired = 0
    for index, block in enumerate(out):
        if block.crc_status in {CrcStatus.ABSENT, CrcStatus.VALID}:
            continue
        out[index] = block.with_computed_crc()
        repaired += 1
    if repaired:
        actions.append(
            RebuildAction(side=side, kind="crc", detail=f"{repaired} checksum(s) recomputed")
        )
    return out


def _rebuild_side(
    side: Side, index: int, options: RebuildOptions, actions: list[RebuildAction]
) -> Side:
    if not side.is_formatted:
        return side

    blocks = list(side.blocks)
    declared = side.declared_file_count or 0

    if options.drop_hidden:
        blocks = _drop_hidden(blocks, index, declared, actions)
    elif options.reveal_hidden:
        blocks = _reveal(blocks, index, declared, actions)

    blocks = _fix_sizes(blocks, index, actions)
    if options.renumber:
        blocks = _renumber(blocks, index, actions)
    blocks = _fix_crcs(blocks, index, actions)

    tail = side.tail
    if not options.keep_tail and side.has_data_after_last_block:
        actions.append(
            RebuildAction(side=index, kind="tail", detail=f"{len(tail)} trailing byte(s) removed")
        )
        tail = b""

    return Side(blocks=tuple(blocks), tail=tail, capacity=side.capacity)


def rebuild(disk: Disk, *, options: RebuildOptions | None = None) -> tuple[Disk, RebuildReport]:
    chosen = options if options is not None else RebuildOptions()
    if chosen.reveal_hidden and chosen.drop_hidden:
        message = "a rebuild can either reveal or drop hidden files, not both"
        raise ValueError(message)

    actions: list[RebuildAction] = []
    sides = tuple(
        _rebuild_side(side, index, chosen, actions) for index, side in enumerate(disk.sides)
    )
    return (
        Disk(sides=sides, header_side_count=disk.header_side_count),
        RebuildReport(actions=tuple(actions)),
    )
