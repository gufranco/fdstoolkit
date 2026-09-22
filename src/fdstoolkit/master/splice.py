from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fdstoolkit.core.blocks import Block, CrcStatus
from fdstoolkit.core.disk import Disk, Side


@dataclass(frozen=True, slots=True)
class Splice:
    side: int
    block: int
    kind: str
    donor: int


@dataclass(frozen=True, slots=True)
class SpliceResult:
    disk: Disk
    splices: tuple[Splice, ...]
    unrepaired: tuple[tuple[int, int], ...]

    @property
    def complete(self) -> bool:
        return not self.unrepaired


def _shape(disk: Disk) -> tuple[int, ...]:
    return (disk.side_count, *(len(side.blocks) for side in disk.sides))


def splice(primary: Disk, donors: Sequence[Disk]) -> SpliceResult:
    if not donors:
        message = "a splice needs at least one donor image"
        raise ValueError(message)

    expected = _shape(primary)
    if any(_shape(donor) != expected for donor in donors):
        message = "a donor has a different shape from the image being repaired"
        raise ValueError(message)

    splices: list[Splice] = []
    unrepaired: list[tuple[int, int]] = []
    sides: list[Side] = []

    for side_index, side in enumerate(primary.sides):
        blocks: list[Block] = []
        for block_index, block in enumerate(side.blocks):
            if block.crc_status is not CrcStatus.MISMATCH:
                blocks.append(block)
                continue

            replacement: Block | None = None
            for donor_index, donor in enumerate(donors):
                candidate = donor.sides[side_index].blocks[block_index]
                if candidate.crc_status is CrcStatus.VALID:
                    replacement = candidate
                    splices.append(
                        Splice(
                            side=side_index,
                            block=block_index,
                            kind=block.kind.name.lower(),
                            donor=donor_index,
                        )
                    )
                    break

            if replacement is None:
                unrepaired.append((side_index, block_index))
                blocks.append(block)
            else:
                blocks.append(replacement)

        sides.append(Side(blocks=tuple(blocks), tail=side.tail, capacity=side.capacity))

    return SpliceResult(
        disk=Disk(sides=tuple(sides), header_side_count=primary.header_side_count),
        splices=tuple(splices),
        unrepaired=tuple(unrepaired),
    )
