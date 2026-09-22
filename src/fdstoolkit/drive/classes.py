from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.codecs.raw import GAP_VALUE, MIN_GAP_VALUES, class_histogram, unpack_raw03

HEALTHY_SHARES: Final = (0.6313, 0.2788, 0.0900)
GLITCH_FLOOR: Final = 0.001
SHIFT_FLOOR: Final = 0.06
MIN_DATA_PULSES: Final = 512
WEIGHTS: Final = (1.0, 1.5, 2.0)
INVALID: Final = 3


class Reading(StrEnum):
    HEALTHY = "healthy"
    SHIFTED = "shifted"
    GLITCHING = "glitching"
    SPARSE = "sparse"


@dataclass(frozen=True, slots=True)
class ClassReport:
    counts: tuple[int, int, int, int]

    @property
    def total(self) -> int:
        return sum(self.counts)

    @property
    def shares(self) -> tuple[float, float, float, float]:
        total = self.total
        if not total:
            return (0.0, 0.0, 0.0, 0.0)
        return (
            self.counts[0] / total,
            self.counts[1] / total,
            self.counts[2] / total,
            self.counts[3] / total,
        )

    @property
    def glitches(self) -> int:
        return self.counts[INVALID]

    @property
    def glitch_rate(self) -> float:
        return self.shares[INVALID]

    @property
    def drift(self) -> float:
        data = self.counts[:INVALID]
        seen = sum(data)
        if not seen:
            return 0.0
        measured = sum(count * weight for count, weight in zip(data, WEIGHTS, strict=True)) / seen
        expected = sum(
            share * weight for share, weight in zip(HEALTHY_SHARES, WEIGHTS, strict=True)
        ) / sum(HEALTHY_SHARES)
        return measured / expected - 1.0

    @property
    def judgeable(self) -> bool:
        return self.total >= MIN_DATA_PULSES

    @property
    def reading(self) -> Reading:
        if self.glitch_rate > GLITCH_FLOOR:
            return Reading.GLITCHING
        if not self.judgeable:
            return Reading.SPARSE
        if abs(self.drift) > SHIFT_FLOOR:
            return Reading.SHIFTED
        return Reading.HEALTHY

    def render(self) -> str:
        names = ("short", "medium", "long", "invalid")
        spread = ", ".join(
            f"{name} {share:.1%}" for name, share in zip(names, self.shares, strict=True)
        )
        if self.reading is Reading.GLITCHING:
            tail = f"{self.glitches} glitch pulses, which do not appear in a good read"
        elif self.reading is Reading.SPARSE:
            tail = (
                f"only {self.total} pulses sit outside the gaps, too few to say "
                "anything about the drive"
            )
        elif self.reading is Reading.SHIFTED:
            way = "slow" if self.drift > 0 else "fast"
            tail = (
                f"the spread sits {abs(self.drift):.1%} off the reference, so the drive reads {way}"
            )
        else:
            tail = "healthy"
        return f"{spread}. {tail}"


def strip_gaps(values: bytes) -> bytes:
    out = bytearray()
    run = 0
    for value in values:
        if value == GAP_VALUE:
            run += 1
            continue
        if run and run < MIN_GAP_VALUES:
            out += bytes(run)
        run = 0
        out.append(value)
    if run and run < MIN_GAP_VALUES:
        out += bytes(run)
    return bytes(out)


def measure_classes(data: bytes, *, packed: bool = False) -> ClassReport:
    values = unpack_raw03(data) if packed else data
    if not values:
        message = "the capture carries no pulse class"
        raise ValueError(message)
    histogram = class_histogram(strip_gaps(bytes(values)))
    return ClassReport(
        counts=(histogram[0], histogram[1], histogram[2], histogram[3]),
    )
