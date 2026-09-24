from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.core.disk import Disk

GOOD_RATE: Final = 0.0
FAULTY_RATE: Final = 0.05
NOISE_FACTOR: Final = 2.0
CLEAR_FACTOR: Final = 4.0


class DriveVerdict(StrEnum):
    GOOD = "good"
    MARGINAL = "marginal"
    FAULTY = "faulty"


class Attribution(StrEnum):
    NEITHER = "neither"
    DRIVE = "drive"
    DISK = "disk"
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class DriveProfile:
    passes: int
    blocks_compared: int
    blocks_wrong: int

    @property
    def error_rate(self) -> float:
        if not self.blocks_compared:
            return 0.0
        return self.blocks_wrong / self.blocks_compared

    @property
    def verdict(self) -> DriveVerdict:
        rate = self.error_rate
        if rate <= GOOD_RATE:
            return DriveVerdict.GOOD
        if rate >= FAULTY_RATE:
            return DriveVerdict.FAULTY
        return DriveVerdict.MARGINAL


def _shape(disk: Disk) -> tuple[int, ...]:
    return (disk.side_count, *(len(side.blocks) for side in disk.sides))


def measure_health(
    reference: Disk,
    reads: Sequence[Disk],
) -> DriveProfile:
    if not reads:
        message = "a drive profile needs at least one read of the reference"
        raise ValueError(message)

    expected = _shape(reference)
    if any(_shape(read) != expected for read in reads):
        message = "a read has a different shape from the reference disk"
        raise ValueError(message)

    compared = wrong = 0
    for read in reads:
        for side_index, side in enumerate(reference.sides):
            for block_index, block in enumerate(side.blocks):
                compared += 1
                if read.sides[side_index].blocks[block_index].payload != block.payload:
                    wrong += 1

    return DriveProfile(
        passes=len(reads),
        blocks_compared=compared,
        blocks_wrong=wrong,
    )


def attribute(profile: DriveProfile, *, observed_rate: float) -> Attribution:
    noise = profile.error_rate
    if observed_rate <= GOOD_RATE:
        return Attribution.NEITHER
    if observed_rate <= noise * NOISE_FACTOR:
        return Attribution.DRIVE
    if observed_rate >= noise * CLEAR_FACTOR:
        return Attribution.DISK
    return Attribution.BOTH
