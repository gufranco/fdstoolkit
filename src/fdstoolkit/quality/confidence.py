from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.core.blocks import Block, CrcStatus
from fdstoolkit.core.disk import Disk
from fdstoolkit.quality.reads import ReadStatistics

CRC_VALID_PRIOR: Final = 0.90
CRC_ABSENT_PRIOR: Final = 0.75
CRC_NULL_PRIOR: Final = 0.50
CRC_MISMATCH_PRIOR: Final = 0.02
LOW_CONFIDENCE: Final = 0.60
FULL_AGREEMENT_READS: Final = 5


class Basis(StrEnum):
    CRC_VALID = "crc valid"
    CRC_NULL = "crc null"
    CRC_ABSENT = "crc absent"
    CRC_MISMATCH = "crc mismatch"
    SINGLE_READ = "single read"
    READS_AGREE = "reads agree"
    READS_DISAGREE = "reads disagree"


@dataclass(frozen=True, slots=True)
class BlockConfidence:
    side: int
    block: int
    kind: str
    confidence: float
    basis: tuple[Basis, ...]

    @property
    def low(self) -> bool:
        return self.confidence < LOW_CONFIDENCE


@dataclass(frozen=True, slots=True)
class ConfidenceReport:
    blocks: tuple[BlockConfidence, ...]

    @property
    def worst(self) -> float:
        if not self.blocks:
            return 0.0
        return min(item.confidence for item in self.blocks)

    @property
    def mean(self) -> float:
        if not self.blocks:
            return 0.0
        return sum(item.confidence for item in self.blocks) / len(self.blocks)

    @property
    def low_confidence_blocks(self) -> tuple[tuple[int, int], ...]:
        return tuple((item.side, item.block) for item in self.blocks if item.low)


_PRIORS: Final = {
    CrcStatus.VALID: (CRC_VALID_PRIOR, Basis.CRC_VALID),
    CrcStatus.NULL: (CRC_NULL_PRIOR, Basis.CRC_NULL),
    CrcStatus.ABSENT: (CRC_ABSENT_PRIOR, Basis.CRC_ABSENT),
    CrcStatus.MISMATCH: (CRC_MISMATCH_PRIOR, Basis.CRC_MISMATCH),
}


def _apply_reads(score: float, share: float, passes: int) -> tuple[float, Basis]:
    if share < 1.0:
        return score * share, Basis.READS_DISAGREE
    weight = min(1.0, (passes - 1) / (FULL_AGREEMENT_READS - 1))
    return score + (1.0 - score) * weight, Basis.READS_AGREE


Lookup = dict[tuple[int, int], tuple[float, int]]


def _lookup(disk: Disk, reads: ReadStatistics | None) -> Lookup:
    if reads is None:
        return {}
    lookup = {(item.side, item.block): (item.modal_share, reads.passes) for item in reads.blocks}
    mine = {
        (side_index, block_index)
        for side_index, side in enumerate(disk.sides)
        for block_index in range(len(side.blocks))
    }
    if set(lookup) != mine:
        message = "the read statistics do not describe this image"
        raise ValueError(message)
    return lookup


def _scored(block: Block, entry: tuple[float, int] | None) -> tuple[float, tuple[Basis, ...]]:
    score, crc_basis = _PRIORS[block.crc_status]
    if entry is None:
        return score, (crc_basis, Basis.SINGLE_READ)
    share, passes = entry
    if block.crc_status is CrcStatus.MISMATCH and share >= 1.0:
        return score, (crc_basis,)
    read_score, read_basis = _apply_reads(score, share, passes)
    return read_score, (crc_basis, read_basis)


def _block_confidence(
    side: int, index: int, block: Block, entry: tuple[float, int] | None
) -> BlockConfidence:
    score, basis = _scored(block, entry)
    return BlockConfidence(
        side=side,
        block=index,
        kind=block.kind.name.lower(),
        confidence=max(0.0, min(1.0, score)),
        basis=basis,
    )


def score_disk(
    disk: Disk,
    *,
    reads: ReadStatistics | None = None,
) -> ConfidenceReport:
    lookup = _lookup(disk, reads)
    return ConfidenceReport(
        blocks=tuple(
            _block_confidence(side_index, block_index, block, lookup.get((side_index, block_index)))
            for side_index, side in enumerate(disk.sides)
            for block_index, block in enumerate(side.blocks)
        )
    )
