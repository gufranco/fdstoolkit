from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from fdstoolkit.core.bitstream import (
    GAP_BITS,
    LEAD_IN_BITS,
    TERMINATOR_SIZE,
    emulated_side_size,
    gap_length,
)
from fdstoolkit.core.blocks import BlockKind, FileHeader
from fdstoolkit.core.crc import CRC_SIZE
from fdstoolkit.core.disk import Disk, Side

BIT_RATE_HZ: Final = 96_400
BITS_PER_BYTE: Final = 8
MIN_FILES_TO_REORDER: Final = 2


def seconds_for(offset: int) -> float:
    return offset * BITS_PER_BYTE / BIT_RATE_HZ


@dataclass(frozen=True, slots=True)
class FilePlacement:
    side: int
    position: int
    file_id: int
    name: str
    size: int
    offset: int
    hidden: bool

    @property
    def seconds_to_reach(self) -> float:
        return seconds_for(self.offset)


@dataclass(frozen=True, slots=True)
class SideLayout:
    side: int
    stream_bytes: int
    dead_bytes: int
    reorder_saving_bytes: int
    note: str
    placements: tuple[FilePlacement, ...]

    @property
    def seconds_to_read(self) -> float:
        return seconds_for(self.stream_bytes)


@dataclass(frozen=True, slots=True)
class LayoutReport:
    sides: tuple[SideLayout, ...]

    @property
    def dead_bytes(self) -> int:
        return sum(side.dead_bytes for side in self.sides)


def _offsets(side: Side) -> list[int]:
    offsets: list[int] = []
    cursor = gap_length(LEAD_IN_BITS) + TERMINATOR_SIZE
    for index, block in enumerate(side.blocks):
        if index:
            cursor += gap_length(GAP_BITS) + TERMINATOR_SIZE
        offsets.append(cursor)
        cursor += block.size + CRC_SIZE
    return offsets


def _pairs(side: Side) -> list[tuple[int, int | None]]:
    found: list[tuple[int, int | None]] = []
    for index, block in enumerate(side.blocks):
        if block.kind is not BlockKind.FILE_HEADER:
            continue
        follows = (
            index + 1 < len(side.blocks) and side.blocks[index + 1].kind is BlockKind.FILE_DATA
        )
        found.append((index, index + 1 if follows else None))
    return found


def _placements(side: Side, index: int) -> tuple[FilePlacement, ...]:
    offsets = _offsets(side)
    declared = side.declared_file_count or 0
    out: list[FilePlacement] = []
    for position, (header_index, data_index) in enumerate(_pairs(side)):
        header = FileHeader.parse(side.blocks[header_index].payload)
        data_size = side.blocks[data_index].size - 1 if data_index is not None else 0
        out.append(
            FilePlacement(
                side=index,
                position=position,
                file_id=header.file_id,
                name=header.name,
                size=data_size,
                offset=offsets[header_index],
                hidden=position >= declared,
            )
        )
    return tuple(out)


def _span(side: Side, header_index: int, data_index: int | None) -> int:
    total = side.blocks[header_index].size + CRC_SIZE + gap_length(GAP_BITS) + TERMINATOR_SIZE
    if data_index is not None:
        total += side.blocks[data_index].size + CRC_SIZE + gap_length(GAP_BITS) + TERMINATOR_SIZE
    return total


def _reorder_saving(side: Side, placements: tuple[FilePlacement, ...]) -> int:
    pairs = _pairs(side)
    if len(pairs) < MIN_FILES_TO_REORDER:
        return 0

    spans = [_span(side, header_index, data_index) for header_index, data_index in pairs]
    start = placements[0].offset

    current = 0
    cursor = start
    for span in spans:
        current += cursor
        cursor += span

    best = 0
    cursor = start
    for span in sorted(spans):
        best += cursor
        cursor += span

    return current - best


def _note(saving: int) -> str:
    if saving == 0:
        return ""
    return (
        f"ordering the files smallest first would cut {saving} bytes from the total distance "
        "the head streams to reach them, which is a measurement rather than a recommendation: "
        "a game may depend on the order it wrote"
    )


def _side_layout(side: Side, index: int) -> SideLayout:
    if not side.is_formatted:
        return SideLayout(
            side=index,
            stream_bytes=0,
            dead_bytes=len(side.tail),
            reorder_saving_bytes=0,
            note="",
            placements=(),
        )

    placements = _placements(side, index)
    saving = _reorder_saving(side, placements)
    return SideLayout(
        side=index,
        stream_bytes=emulated_side_size(side),
        dead_bytes=len(side.tail),
        reorder_saving_bytes=saving,
        note=_note(saving),
        placements=placements,
    )


def layout_of(disk: Disk) -> LayoutReport:
    return LayoutReport(
        sides=tuple(_side_layout(side, index) for index, side in enumerate(disk.sides))
    )
