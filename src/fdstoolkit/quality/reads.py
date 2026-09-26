from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.core.disk import Disk
from fdstoolkit.quality.consensus import Matched, match_side, require_same_sides

MIN_READS: Final = 2
DECAY_RATIO: Final = 3.0


class Decay(StrEnum):
    NONE = "none"
    LOSS = "loss"
    GAIN = "gain"
    MIXED = "mixed"


@dataclass(frozen=True, slots=True)
class BlockReads:
    side: int
    block: int
    kind: str
    variants: int
    modal_share: float
    bits_differing: int
    ones_lost: int
    ones_gained: int
    missing: int = 0

    @property
    def flip_rate(self) -> float:
        return 1.0 - self.modal_share

    @property
    def stable(self) -> bool:
        return self.variants == 1


@dataclass(frozen=True, slots=True)
class ReadStatistics:
    passes: int
    blocks: tuple[BlockReads, ...]

    @property
    def missing(self) -> tuple[tuple[int, int, int], ...]:
        return tuple((item.side, item.block, item.missing) for item in self.blocks if item.missing)

    @property
    def unstable_blocks(self) -> tuple[tuple[int, int], ...]:
        return tuple((item.side, item.block) for item in self.blocks if not item.stable)

    @property
    def stability(self) -> float:
        if not self.blocks:
            return 1.0
        return sum(item.modal_share for item in self.blocks) / len(self.blocks)

    @property
    def ones_lost(self) -> int:
        return sum(item.ones_lost for item in self.blocks)

    @property
    def ones_gained(self) -> int:
        return sum(item.ones_gained for item in self.blocks)

    @property
    def decay(self) -> Decay:
        lost, gained = self.ones_lost, self.ones_gained
        if not lost and not gained:
            return Decay.NONE
        if gained and lost <= gained * DECAY_RATIO and gained <= lost * DECAY_RATIO:
            return Decay.MIXED
        return Decay.LOSS if lost > gained else Decay.GAIN


def _bit_drift(modal: bytes, other: bytes) -> tuple[int, int, int]:
    differing = lost = gained = 0
    for left, right in zip(modal, other, strict=False):
        delta = left ^ right
        if not delta:
            continue
        for bit in range(8):
            if not (delta >> bit) & 1:
                continue
            differing += 1
            if (left >> bit) & 1:
                lost += 1
            else:
                gained += 1
    return differing, lost, gained


def _block_reads(side: int, block: int, matched: Matched) -> BlockReads:
    payloads = [copy.payload for copy in matched.copies]
    counts = Counter(payloads)
    modal, votes = counts.most_common(1)[0]
    differing = lost = gained = 0
    for payload in payloads:
        if payload == modal:
            continue
        delta, one_lost, one_gained = _bit_drift(modal, payload)
        differing += delta
        lost += one_lost
        gained += one_gained
    return BlockReads(
        side=side,
        block=block,
        kind=matched.block.kind.name.lower(),
        variants=len(counts),
        modal_share=votes / len(payloads),
        bits_differing=differing,
        ones_lost=lost,
        ones_gained=gained,
        missing=matched.missing,
    )


def compare_reads(disks: Sequence[Disk]) -> ReadStatistics:
    if len(disks) < MIN_READS:
        message = f"read statistics need at least two reads, got {len(disks)}"
        raise ValueError(message)
    require_same_sides(disks, "reads")
    blocks = tuple(
        _block_reads(side, block, matched)
        for side in range(disks[0].side_count)
        for block, matched in enumerate(match_side([disk.sides[side] for disk in disks]))
    )
    return ReadStatistics(passes=len(disks), blocks=blocks)
