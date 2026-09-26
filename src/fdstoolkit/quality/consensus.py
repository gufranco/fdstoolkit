from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.core.blocks import Block, CrcStatus
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.drive.vote import keyed

MIN_DUMPS: Final = 2


class BlockVerdict(StrEnum):
    AGREED = "agreed"
    MAJORITY = "majority"
    CHECKSUM = "checksum"
    TIED = "tied"


@dataclass(frozen=True, slots=True)
class BlockStability:
    side: int
    block: int
    kind: str
    verdict: BlockVerdict
    variants: int
    agreement: float
    missing: int = 0

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

    @property
    def missing(self) -> tuple[tuple[int, int, int], ...]:
        return tuple(
            (entry.side, entry.block, entry.missing) for entry in self.stability if entry.missing
        )


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    identical: bool
    differing_blocks: tuple[tuple[int, int], ...]
    summary: str


@dataclass(frozen=True, slots=True)
class Matched:
    block: Block
    copies: tuple[Block, ...]
    missing: int


def match_side(sides: Sequence[Side]) -> tuple[Matched, ...]:
    skeleton = max(sides, key=lambda side: len(side.blocks))
    maps = [dict(zip(keyed(side.blocks), side.blocks, strict=True)) for side in sides]
    return tuple(
        Matched(
            block=block,
            copies=tuple(found[key] for found in maps if key in found),
            missing=sum(1 for found in maps if key not in found),
        )
        for key, block in zip(keyed(skeleton.blocks), skeleton.blocks, strict=True)
    )


def require_same_sides(disks: Sequence[Disk], what: str) -> None:
    if any(disk.side_count != disks[0].side_count for disk in disks[1:]):
        message = f"the {what} have different numbers of sides, so they are not the same disk"
        raise ValueError(message)


def _passing(copies: Sequence[Block]) -> list[bytes]:
    return [block.payload for block in copies if block.crc_status is CrcStatus.VALID]


def _decide(copies: Sequence[Block]) -> tuple[Block, BlockVerdict]:
    payloads = [block.payload for block in copies]
    counts = Counter(payloads)
    if len(counts) == 1:
        return copies[0], BlockVerdict.AGREED
    passing = Counter(_passing(copies))
    if len(passing) == 1:
        chosen = next(iter(passing))
        return copies[payloads.index(chosen)], BlockVerdict.CHECKSUM
    winner, votes = counts.most_common(1)[0]
    if votes == counts.most_common(2)[1][1]:
        return copies[0], BlockVerdict.TIED
    return copies[payloads.index(winner)], BlockVerdict.MAJORITY


def _merge_side(side_index: int, sides: Sequence[Side]) -> tuple[Side, list[BlockStability]]:
    blocks: list[Block] = []
    stability: list[BlockStability] = []
    for block_index, matched in enumerate(match_side(sides)):
        chosen, verdict = _decide(matched.copies)
        payloads = [copy.payload for copy in matched.copies]
        stability.append(
            BlockStability(
                side=side_index,
                block=block_index,
                kind=matched.block.kind.name.lower(),
                verdict=verdict,
                variants=len(set(payloads)),
                agreement=payloads.count(chosen.payload) / len(payloads),
                missing=matched.missing,
            )
        )
        blocks.append(chosen)
    first = sides[0]
    return Side(blocks=tuple(blocks), tail=first.tail, capacity=first.capacity), stability


def build_consensus(disks: Sequence[Disk]) -> ConsensusResult:
    if len(disks) < MIN_DUMPS:
        message = f"a consensus needs at least two dumps, got {len(disks)}"
        raise ValueError(message)
    require_same_sides(disks, "dumps")

    merged = [
        _merge_side(index, [disk.sides[index] for disk in disks])
        for index in range(disks[0].side_count)
    ]
    stability = tuple(entry for _, entries in merged for entry in entries)
    return ConsensusResult(
        disk=Disk(
            sides=tuple(side for side, _ in merged),
            header_side_count=disks[0].header_side_count,
        ),
        verdicts=tuple(entry.verdict for entry in stability),
        disagreements=tuple((entry.side, entry.block) for entry in stability if not entry.stable),
        stability=stability,
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
