from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstk.core.blocks import Block
from fdstk.core.disk import Disk, Side

MIN_DUMPS: Final = 2


class BlockVerdict(StrEnum):
    AGREED = "agreed"
    MAJORITY = "majority"
    TIED = "tied"


@dataclass(frozen=True, slots=True)
class BlockStability:
    side: int
    block: int
    kind: str
    verdict: BlockVerdict
    variants: int
    agreement: float

    @property
    def stable(self) -> bool:
        return self.verdict is BlockVerdict.AGREED


@dataclass(frozen=True, slots=True)
class ConsensusResult:
    disk: Disk
    verdicts: tuple[BlockVerdict, ...]
    disagreements: tuple[tuple[int, int], ...]
    stability: tuple[BlockStability, ...] = ()

    @property
    def stable(self) -> bool:
        return not self.disagreements


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    identical: bool
    differing_blocks: tuple[tuple[int, int], ...]
    summary: str


def _shape(disk: Disk) -> tuple[int, ...]:
    return (disk.side_count, *(len(side.blocks) for side in disk.sides))


def _decide(payloads: Sequence[bytes]) -> tuple[bytes, BlockVerdict]:
    counts = Counter(payloads)
    winner, votes = counts.most_common(1)[0]
    if len(counts) == 1:
        return winner, BlockVerdict.AGREED
    runner_up = counts.most_common(2)[1][1]
    if votes == runner_up:
        return payloads[0], BlockVerdict.TIED
    return winner, BlockVerdict.MAJORITY


def build_consensus(disks: Sequence[Disk]) -> ConsensusResult:
    if len(disks) < MIN_DUMPS:
        message = f"a consensus needs at least two dumps, got {len(disks)}"
        raise ValueError(message)

    reference = _shape(disks[0])
    if any(_shape(disk) != reference for disk in disks[1:]):
        message = "the dumps have different shapes, so they cannot be merged"
        raise ValueError(message)

    verdicts: list[BlockVerdict] = []
    disagreements: list[tuple[int, int]] = []
    stability: list[BlockStability] = []
    sides: list[Side] = []

    for side_index, side in enumerate(disks[0].sides):
        blocks: list[Block] = []
        for block_index, block in enumerate(side.blocks):
            payloads = [disk.sides[side_index].blocks[block_index].payload for disk in disks]
            chosen, verdict = _decide(payloads)
            verdicts.append(verdict)
            counts = Counter(payloads)
            stability.append(
                BlockStability(
                    side=side_index,
                    block=block_index,
                    kind=block.kind.name.lower(),
                    verdict=verdict,
                    variants=len(counts),
                    agreement=counts[chosen] / len(payloads),
                )
            )
            if verdict is not BlockVerdict.AGREED:
                disagreements.append((side_index, block_index))
            blocks.append(
                Block(kind=block.kind, payload=chosen, stored_crc=block.stored_crc),
            )
        sides.append(Side(blocks=tuple(blocks), tail=side.tail, capacity=side.capacity))

    return ConsensusResult(
        disk=Disk(sides=tuple(sides), header_side_count=disks[0].header_side_count),
        verdicts=tuple(verdicts),
        disagreements=tuple(disagreements),
        stability=tuple(stability),
    )


def compare_images(first: Disk, second: Disk) -> ComparisonReport:
    if first.side_count != second.side_count:
        return ComparisonReport(
            identical=False,
            differing_blocks=(),
            summary=(f"side count differs: {first.side_count} against {second.side_count}"),
        )

    differing: list[tuple[int, int]] = []
    for side_index, (left, right) in enumerate(zip(first.sides, second.sides, strict=True)):
        if len(left.blocks) != len(right.blocks):
            return ComparisonReport(
                identical=False,
                differing_blocks=(),
                summary=(
                    f"block count differs on side {side_index}: "
                    f"{len(left.blocks)} against {len(right.blocks)}"
                ),
            )
        differing.extend(
            (side_index, block_index)
            for block_index, (one, other) in enumerate(zip(left.blocks, right.blocks, strict=True))
            if one.payload != other.payload
        )

    if not differing:
        return ComparisonReport(identical=True, differing_blocks=(), summary="identical")

    return ComparisonReport(
        identical=False,
        differing_blocks=tuple(differing),
        summary=f"{len(differing)} block(s) differ",
    )
