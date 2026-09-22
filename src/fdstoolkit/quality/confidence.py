from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.core.blocks import CrcStatus
from fdstoolkit.core.disk import Disk
from fdstoolkit.flux.analysis import HEALTHY_MARGIN
from fdstoolkit.quality.reads import ReadStatistics

CRC_VALID_PRIOR: Final = 0.90
CRC_ABSENT_PRIOR: Final = 0.75
CRC_NULL_PRIOR: Final = 0.50
CRC_MISMATCH_PRIOR: Final = 0.02
LOW_CONFIDENCE: Final = 0.60
FULL_AGREEMENT_READS: Final = 5
MARGIN_LIFT: Final = 0.5
MARGIN_FLOOR: Final = 0.3


class Basis(StrEnum):
    CRC_VALID = "crc valid"
    CRC_NULL = "crc null"
    CRC_ABSENT = "crc absent"
    CRC_MISMATCH = "crc mismatch"
    SINGLE_READ = "single read"
    READS_AGREE = "reads agree"
    READS_DISAGREE = "reads disagree"
    FLUX_CLEAR = "flux margin clear"
    FLUX_MARGINAL = "flux margin narrow"


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


def _apply_margin(score: float, margin: float) -> tuple[float, Basis]:
    if margin >= HEALTHY_MARGIN:
        return score + (1.0 - score) * MARGIN_LIFT * margin, Basis.FLUX_CLEAR
    scale = MARGIN_FLOOR + (1.0 - MARGIN_FLOOR) * (margin / HEALTHY_MARGIN)
    return score * scale, Basis.FLUX_MARGINAL


def score_disk(
    disk: Disk,
    *,
    reads: ReadStatistics | None = None,
    margin: float | None = None,
) -> ConfidenceReport:
    lookup: dict[tuple[int, int], tuple[float, int]] = {}
    if reads is not None:
        lookup = {
            (item.side, item.block): (item.modal_share, reads.passes) for item in reads.blocks
        }
        shape = {(side, block) for side, block in lookup}
        mine = {
            (side_index, block_index)
            for side_index, side in enumerate(disk.sides)
            for block_index in range(len(side.blocks))
        }
        if shape != mine:
            message = "the read statistics do not describe this image"
            raise ValueError(message)

    blocks: list[BlockConfidence] = []
    for side_index, side in enumerate(disk.sides):
        for block_index, block in enumerate(side.blocks):
            score, crc_basis = _PRIORS[block.crc_status]
            basis = [crc_basis]

            entry = lookup.get((side_index, block_index))
            if entry is None:
                basis.append(Basis.SINGLE_READ)
            else:
                share, passes = entry
                score, read_basis = _apply_reads(score, share, passes)
                basis.append(read_basis)

            if margin is not None:
                score, margin_basis = _apply_margin(score, margin)
                basis.append(margin_basis)

            blocks.append(
                BlockConfidence(
                    side=side_index,
                    block=block_index,
                    kind=block.kind.name.lower(),
                    confidence=max(0.0, min(1.0, score)),
                    basis=tuple(basis),
                )
            )

    return ConfidenceReport(blocks=tuple(blocks))
