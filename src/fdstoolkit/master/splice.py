from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fdstoolkit.core.blocks import Block, CrcStatus
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.core.diskinfo import CONTENT_PROFILE, mask_disk_info


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


@dataclass(frozen=True, slots=True)
class _SplicedSide:
    side: Side
    splices: tuple[Splice, ...]
    unrepaired: tuple[tuple[int, int], ...]


def _shape(disk: Disk) -> tuple[int, ...]:
    return (disk.side_count, *(len(side.blocks) for side in disk.sides))


def _same_info(mine: Side, theirs: Side) -> bool:
    if not (mine.is_formatted and theirs.is_formatted):
        return True
    ours, other = mine.blocks[0], theirs.blocks[0]
    if CrcStatus.MISMATCH in {ours.crc_status, other.crc_status}:
        return True
    masked = mask_disk_info(ours.payload, CONTENT_PROFILE)
    return masked == mask_disk_info(other.payload, CONTENT_PROFILE)


def _check_donors(primary: Disk, donors: Sequence[Disk]) -> None:
    if not donors:
        message = "a splice needs at least one donor image"
        raise ValueError(message)
    if any(_shape(donor) != _shape(primary) for donor in donors):
        message = "a donor has a different shape from the image being repaired"
        raise ValueError(message)
    for number, donor in enumerate(donors, start=1):
        pairs = enumerate(zip(primary.sides, donor.sides, strict=True))
        side = next(
            (index for index, (mine, theirs) in pairs if not _same_info(mine, theirs)), None
        )
        if side is not None:
            message = (
                f"donor {number} holds another disk: its side {side} disk information differs "
                "from the image's, so none of its blocks belong here"
            )
            raise ValueError(message)


def _replacement(
    block: Block, side: int, index: int, donors: Sequence[Disk]
) -> tuple[Block, int] | None:
    for number, donor in enumerate(donors):
        candidate = donor.sides[side].blocks[index]
        if candidate.crc_status is CrcStatus.VALID and candidate.kind is block.kind:
            return candidate, number
    return None


def _splice_side(side_index: int, side: Side, donors: Sequence[Disk]) -> _SplicedSide:
    blocks: list[Block] = []
    splices: list[Splice] = []
    unrepaired: list[tuple[int, int]] = []
    for index, block in enumerate(side.blocks):
        found = None
        if block.crc_status is CrcStatus.MISMATCH:
            found = _replacement(block, side_index, index, donors)
            unrepaired.extend([(side_index, index)] if found is None else [])
        if found is not None:
            splices.append(Splice(side_index, index, block.kind.name.lower(), found[1]))
        blocks.append(block if found is None else found[0])
    replaced = Side(blocks=tuple(blocks), tail=side.tail, capacity=side.capacity)
    return _SplicedSide(replaced, tuple(splices), tuple(unrepaired))


def splice(primary: Disk, donors: Sequence[Disk]) -> SpliceResult:
    _check_donors(primary, donors)
    sides = [_splice_side(index, side, donors) for index, side in enumerate(primary.sides)]
    return SpliceResult(
        disk=Disk(
            sides=tuple(entry.side for entry in sides),
            header_side_count=primary.header_side_count,
        ),
        splices=tuple(item for entry in sides for item in entry.splices),
        unrepaired=tuple(item for entry in sides for item in entry.unrepaired),
    )
