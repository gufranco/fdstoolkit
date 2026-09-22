from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.core.disk import Disk

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


def _shape(disk: Disk) -> tuple[int, ...]:
    return (disk.side_count, *(len(side.blocks) for side in disk.sides))


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


def compare_reads(disks: Sequence[Disk]) -> ReadStatistics:
    if len(disks) < MIN_READS:
        message = f"read statistics need at least two reads, got {len(disks)}"
        raise ValueError(message)

    reference = _shape(disks[0])
    if any(_shape(disk) != reference for disk in disks[1:]):
        message = "the reads have different shapes, so they are not the same disk"
        raise ValueError(message)

    blocks: list[BlockReads] = []
    for side_index, side in enumerate(disks[0].sides):
        for block_index, block in enumerate(side.blocks):
            payloads = [disk.sides[side_index].blocks[block_index].payload for disk in disks]
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
            blocks.append(
                BlockReads(
                    side=side_index,
                    block=block_index,
                    kind=block.kind.name.lower(),
                    variants=len(counts),
                    modal_share=votes / len(payloads),
                    bits_differing=differing,
                    ones_lost=lost,
                    ones_gained=gained,
                )
            )

    return ReadStatistics(passes=len(disks), blocks=tuple(blocks))
