from __future__ import annotations

from dataclasses import dataclass

from fdstk.core.disk import Disk, Side


@dataclass(frozen=True, slots=True)
class RemovedTail:
    side: int
    bytes_removed: int
    data: bytes


def clean_trailing_data(disk: Disk) -> tuple[Disk, tuple[RemovedTail, ...]]:
    sides: list[Side] = []
    removed: list[RemovedTail] = []

    for index, side in enumerate(disk.sides):
        if not side.has_data_after_last_block:
            sides.append(side)
            continue
        removed.append(
            RemovedTail(side=index, bytes_removed=len(side.tail), data=side.tail),
        )
        sides.append(Side(blocks=side.blocks, tail=b"", capacity=side.capacity))

    return (
        Disk(sides=tuple(sides), header_side_count=disk.header_side_count),
        tuple(removed),
    )
