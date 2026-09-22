from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.flux.analysis import fit_family

SMOOTH_SHARE: Final = 0.02
MIN_WINDOW: Final = 8
STEADY_WOW: Final = 0.005
STEADY_DRIFT: Final = 0.01
EXCELLENT_WOW: Final = 0.002
POOR_WOW: Final = 0.04


class Motion(StrEnum):
    STEADY = "steady"
    PERIODIC = "periodic"
    DRIFTING = "drifting"


@dataclass(frozen=True, slots=True)
class StabilityReport:
    cell_ns: float
    wow_flutter: float
    drift: float
    fastest_ns: float
    slowest_ns: float
    samples: int

    @property
    def spread(self) -> float:
        if self.cell_ns <= 0:
            return 0.0
        return (self.slowest_ns - self.fastest_ns) / self.cell_ns

    @property
    def motion(self) -> Motion:
        if abs(self.drift) > STEADY_DRIFT and abs(self.drift) > self.wow_flutter:
            return Motion.DRIFTING
        if self.wow_flutter > STEADY_WOW:
            return Motion.PERIODIC
        return Motion.STEADY

    @property
    def quality(self) -> float:
        if self.wow_flutter <= EXCELLENT_WOW:
            return 1.0
        if self.wow_flutter >= POOR_WOW:
            return 0.0
        span = POOR_WOW - EXCELLENT_WOW
        return 1.0 - (self.wow_flutter - EXCELLENT_WOW) / span

    def render(self) -> str:
        return (
            f"{self.motion.value}, wow and flutter {self.wow_flutter:.2%}, "
            f"drift {self.drift:+.2%}, spread {self.spread:.2%}"
        )


def cell_series(
    intervals: Sequence[int],
    *,
    base_ns: float,
    ratios: Sequence[float],
) -> tuple[float, ...]:
    if not intervals:
        message = "a capture with no interval has no cell series"
        raise ValueError(message)
    return tuple(
        value / min(ratios, key=lambda ratio: abs(value - base_ns * ratio)) for value in intervals
    )


def _smooth(series: Sequence[float], window: int) -> list[float]:
    if window <= 1 or len(series) < window:
        return list(series)
    out: list[float] = []
    running = sum(series[:window])
    out.append(running / window)
    for index in range(window, len(series)):
        running += series[index] - series[index - window]
        out.append(running / window)
    return out


def measure_stability(intervals: Sequence[int]) -> StabilityReport:
    if not intervals:
        message = "a capture with no interval has no stability"
        raise ValueError(message)

    base, ratios, _ = fit_family(intervals)
    series = cell_series(intervals, base_ns=base, ratios=ratios)
    window = max(MIN_WINDOW, int(len(series) * SMOOTH_SHARE))
    smoothed = _smooth(series, window)

    centre = statistics.fmean(smoothed)
    if centre <= 0:
        centre = base
    deviation = statistics.pstdev(smoothed) if len(smoothed) > 1 else 0.0

    half = max(1, len(smoothed) // 4)
    head = statistics.fmean(smoothed[:half])
    tail = statistics.fmean(smoothed[-half:])

    return StabilityReport(
        cell_ns=centre,
        wow_flutter=deviation / centre,
        drift=(tail - head) / centre,
        fastest_ns=min(smoothed),
        slowest_ns=max(smoothed),
        samples=len(series),
    )
