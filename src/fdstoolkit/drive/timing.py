from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from statistics import fmean, pstdev
from typing import Final, Protocol

from fdstoolkit.codecs.raw import (
    NOMINAL_SHORT,
    decode_raw03,
    pack_raw03,
    quantise,
)
from fdstoolkit.drive.align import good_block

SMALLEST_COUNT: Final = 16
ZERO_SHARE: Final = 0.01
PEAK_WINDOW: Final = 2
PEAK_SHARE: Final = 0.02
COUNT_RANGE: Final = 256
CLASS_NAMES: Final = ("short", "medium", "long")
PERCENT: Final = 100
CAPTURE_CLOCK_KHZ: Final = 6000
NOMINAL_RATE_KHZ: Final = 96.4
RATE_TOLERANCE: Final = 0.10
CELLS_PER_CLASS: Final = (1.0, 1.5, 2.0)


class Nature(StrEnum):
    TIMING = "pulse timing"
    UNDECODED = "what looks like pulse timing, though no block decoded from it"
    CLASSES = "pulse classes only"
    NOTHING = "no data"


COUNTED: Final = frozenset({Nature.TIMING, Nature.UNDECODED})


class SideReader(Protocol):
    def read_raw_side(self, *, what: str) -> bytes: ...


def _short_nominal(counts: bytes) -> int | None:
    usable = Counter(count for count in counts if count >= SMALLEST_COUNT)
    total = sum(usable.values())
    smoothed = [
        sum(usable[value + step] for step in range(-PEAK_WINDOW, PEAK_WINDOW + 1))
        for value in range(COUNT_RANGE)
    ]
    peaks = [
        value
        for value in range(SMALLEST_COUNT, COUNT_RANGE - 1)
        if smoothed[value] >= smoothed[value - 1]
        and smoothed[value] > smoothed[value + 1]
        and smoothed[value] >= total * PEAK_SHARE
    ]
    return peaks[0] if peaks else None


def _scale(counts: bytes) -> float:
    nominal = _short_nominal(counts)
    return nominal / NOMINAL_SHORT if nominal else 1.0


def classes_of(counts: bytes) -> bytes:
    return quantise(counts, _scale(counts))


def classify(data: bytes) -> Nature:
    if not data:
        return Nature.NOTHING
    if data.count(0) > len(data) * ZERO_SHARE or _short_nominal(data) is None:
        return Nature.CLASSES
    side, _ = decode_raw03(quantise(data, _scale(data)))
    return Nature.TIMING if any(good_block(block) for block in side.blocks) else Nature.UNDECODED


@dataclass(frozen=True, slots=True)
class Timing:
    means: tuple[float, float, float]
    spreads: tuple[float, float, float]

    @property
    def spread_percent(self) -> float:
        shares = [
            spread / mean for mean, spread in zip(self.means, self.spreads, strict=True) if mean
        ]
        return fmean(shares) * PERCENT if shares else 0.0

    @property
    def rate_khz(self) -> float:
        cells = [
            mean / width for mean, width in zip(self.means, CELLS_PER_CLASS, strict=True) if mean
        ]
        return CAPTURE_CLOCK_KHZ / fmean(cells) if cells else 0.0

    @property
    def rate_offset_percent(self) -> float:
        return (self.rate_khz / NOMINAL_RATE_KHZ - 1) * PERCENT

    @property
    def rate_in_tolerance(self) -> bool:
        return abs(self.rate_offset_percent) <= RATE_TOLERANCE * PERCENT

    def as_dict(self) -> dict[str, object]:
        return {
            "means": list(self.means),
            "spreads": list(self.spreads),
            "spread_percent": round(self.spread_percent, 3),
            "rate_khz": round(self.rate_khz, 3),
            "rate_offset_percent": round(self.rate_offset_percent, 3),
            "rate_in_tolerance": self.rate_in_tolerance,
        }

    def _rate_line(self) -> str:
        where = "inside" if self.rate_in_tolerance else "outside"
        return (
            f"bit rate {self.rate_khz:.1f} kHz, {self.rate_offset_percent:+.1f}% from "
            f"{NOMINAL_RATE_KHZ} kHz at an assumed {CAPTURE_CLOCK_KHZ // 1000} MHz capture clock, "
            f"{where} the ±{RATE_TOLERANCE * PERCENT:.0f}% the RAM adapter accepts"
        )

    def render(self) -> str:
        classes = ", ".join(
            f"{name} {mean:.1f}±{spread:.1f}"
            for name, mean, spread in zip(CLASS_NAMES, self.means, self.spreads, strict=True)
        )
        return (
            f"timing: {classes} counts, spread {self.spread_percent:.1f}%, smaller is better; "
            f"{self._rate_line()}"
        )


def measure_timing(counts: bytes) -> Timing:
    classes = quantise(counts, _scale(counts))
    groups = [
        [count for count, kind in zip(counts, classes, strict=True) if kind == index]
        for index in range(3)
    ]
    means = tuple(fmean(group) if group else 0.0 for group in groups)
    spreads = tuple(pstdev(group) if len(group) > 1 else 0.0 for group in groups)
    return Timing(
        means=(means[0], means[1], means[2]), spreads=(spreads[0], spreads[1], spreads[2])
    )


def _no_timings() -> list[Timing]:
    return []


@dataclass(slots=True)
class TimingReader:
    reader: SideReader
    note: Callable[[str], None]
    timings: list[Timing] = field(default_factory=_no_timings)

    def read_raw_side(self, *, what: str) -> bytes:
        data = self.reader.read_raw_side(what=what)
        if classify(data) not in COUNTED:
            return data
        timing = measure_timing(data)
        self.timings.append(timing)
        self.note(timing.render())
        return pack_raw03(classes_of(data))
