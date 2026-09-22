from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from fdstoolkit.flux.model import (
    LONG_NS,
    MEDIUM_NS,
    NS_PER_SECOND,
    SHORT_NS,
    FluxCapture,
)

RATIOS: Final = (1.0, 1.5, 2.0)
GCR_RATIOS: Final = (1.0, 2.0, 3.0)
FAMILIES: Final[dict[str, tuple[float, ...]]] = {"mfm": RATIOS, "gcr": GCR_RATIOS}
STRAY_MARGIN: Final = 0.25
MARGIN_PERCENTILE: Final = 0.01
SEEDS: Final = (float(SHORT_NS), float(MEDIUM_NS), float(LONG_NS))
OUTLIER_FACTOR: Final = 2.0
HEALTHY_MARGIN: Final = 0.35
DEFAULT_BUCKET_NS: Final = 250
FIT_SAMPLES: Final = 4096
FIT_STEPS: Final = 160
FIT_LOW: Final = 0.75
FIT_HIGH: Final = 1.60
MIN_FOR_SPREAD: Final = 2


def histogram(intervals: Sequence[int], *, bucket_ns: int = DEFAULT_BUCKET_NS) -> dict[int, int]:
    if bucket_ns <= 0:
        message = "a histogram bucket must be positive"
        raise ValueError(message)
    counts: dict[int, int] = {}
    for interval in intervals:
        bucket = interval // bucket_ns
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts


@dataclass(frozen=True, slots=True)
class Cluster:
    label: int
    centre_ns: float
    spread_ns: float
    count: int


@dataclass(frozen=True, slots=True)
class Separation:
    lower: int
    upper: int
    boundary_ns: float
    closest_ns: float
    margin: float
    strays: int = 0


@dataclass(frozen=True, slots=True)
class IntervalReport:
    pulses: int
    clusters: tuple[Cluster, ...]
    separations: tuple[Separation, ...]
    outliers: int
    rpm: float | None
    base_ns: float = 0.0

    @property
    def bit_rate_hz(self) -> float:
        if self.base_ns <= 0:
            return 0.0
        return NS_PER_SECOND / self.base_ns

    @property
    def worst_margin(self) -> float:
        if not self.separations:
            return 0.0
        return min(item.margin for item in self.separations)

    @property
    def healthy(self) -> bool:
        return self.worst_margin >= HEALTHY_MARGIN and not self.outliers


@dataclass(frozen=True, slots=True)
class TrackReport:
    index: int
    revolutions: tuple[IntervalReport, ...]

    @property
    def worst_margin(self) -> float:
        return min(report.worst_margin for report in self.revolutions)

    @property
    def healthy(self) -> bool:
        return all(report.healthy for report in self.revolutions)

    @property
    def rpm_spread(self) -> float:
        speeds = [report.rpm for report in self.revolutions if report.rpm is not None]
        if len(speeds) < MIN_FOR_SPREAD:
            return 0.0
        return statistics.pstdev(speeds)


@dataclass(frozen=True, slots=True)
class CaptureReport:
    tracks: tuple[TrackReport, ...]

    @property
    def worst_margin(self) -> float:
        return min(track.worst_margin for track in self.tracks)

    @property
    def worst_track(self) -> int:
        return min(self.tracks, key=lambda track: track.worst_margin).index

    @property
    def healthy(self) -> bool:
        return all(track.healthy for track in self.tracks)


def _sample(intervals: Sequence[int]) -> Sequence[int]:
    if len(intervals) <= FIT_SAMPLES:
        return intervals
    stride = len(intervals) // FIT_SAMPLES
    return intervals[::stride]


def _residual(intervals: Sequence[int], base: float, ratios: Sequence[float]) -> float:
    centres = [base * ratio for ratio in ratios]
    total = 0.0
    for interval in intervals:
        nearest = min(centres, key=lambda centre: abs(interval - centre))
        total += (interval - nearest) ** 2
    return total


def estimate_base_ns(intervals: Sequence[int]) -> float:
    return fit_family(intervals)[0]


def _best_base(sample: Sequence[int], anchor: float, ratios: Sequence[float]) -> float:
    low = anchor * FIT_LOW / ratios[-1]
    high = anchor * FIT_HIGH
    step = (high - low) / FIT_STEPS
    if step <= 0:
        return float(anchor)
    candidates = [low + step * index for index in range(FIT_STEPS + 1)]
    return min(candidates, key=lambda value: _residual(sample, value, ratios))


def fit_family(intervals: Sequence[int]) -> tuple[float, tuple[float, ...], str]:
    if not intervals:
        message = "a flux stream with no interval cannot be analysed"
        raise ValueError(message)
    sample = _sample(intervals)
    anchor = statistics.median(sample)

    fits: list[tuple[float, float, tuple[float, ...], str]] = []
    for name, ratios in FAMILIES.items():
        base = _best_base(sample, anchor, ratios)
        fits.append((_residual(sample, base, ratios), base, ratios, name))

    _, base, ratios, name = min(fits, key=lambda fit: fit[0])
    return base, ratios, name


def _assign(intervals: Sequence[int], centres: Sequence[float]) -> list[list[int]]:
    groups: list[list[int]] = [[] for _ in centres]
    for interval in intervals:
        nearest = min(range(len(centres)), key=lambda index: abs(interval - centres[index]))
        groups[nearest].append(interval)
    return groups


def _fit(intervals: Sequence[int]) -> tuple[list[float], list[list[int]]]:
    base, ratios, _ = fit_family(intervals)
    centres = [base * ratio for ratio in ratios]
    groups = _assign(intervals, centres)
    centres = [
        statistics.fmean(group) if group else centres[index] for index, group in enumerate(groups)
    ]
    groups = _assign(intervals, centres)
    return centres, groups


def _margin(samples: Sequence[int], boundary: float, half: float) -> tuple[float, int, float]:
    if half <= 0 or not samples:
        return 0.0, 0, boundary
    distances = sorted(min(1.0, abs(value - boundary) / half) for value in samples)
    index = min(len(distances) - 1, int(MARGIN_PERCENTILE * len(distances)))
    strays = sum(1 for value in distances if value < STRAY_MARGIN)
    closest = min(samples, key=lambda value: abs(value - boundary))
    return distances[index], strays, float(closest)


def _separations(clusters: Sequence[Cluster], groups: Sequence[Sequence[int]]) -> list[Separation]:
    out: list[Separation] = []
    for index in range(len(clusters) - 1):
        low, high = clusters[index], clusters[index + 1]
        boundary = (low.centre_ns + high.centre_ns) / 2
        half = (high.centre_ns - low.centre_ns) / 2
        samples = [*groups[index], *groups[index + 1]]
        margin, strays, closest = _margin(samples, boundary, half)
        out.append(
            Separation(
                lower=low.label,
                upper=high.label,
                boundary_ns=boundary,
                closest_ns=closest,
                margin=margin,
                strays=strays,
            )
        )
    return out


def analyse_intervals(
    intervals: Sequence[int],
    *,
    revolution_ns: int | None = None,
) -> IntervalReport:
    if not intervals:
        message = "a flux stream with no interval cannot be analysed"
        raise ValueError(message)

    base = estimate_base_ns(intervals)
    seeds = [base * ratio for ratio in RATIOS]
    tolerance = OUTLIER_FACTOR * base
    inliers = [
        value for value in intervals if min(abs(value - centre) for centre in seeds) <= tolerance
    ]
    outliers = len(intervals) - len(inliers)

    centres, groups = _fit(inliers or list(intervals))
    clusters = tuple(
        Cluster(
            label=index,
            centre_ns=centres[index],
            spread_ns=statistics.pstdev(group) if len(group) > 1 else 0.0,
            count=len(group),
        )
        for index, group in enumerate(groups)
    )
    rpm = None if revolution_ns is None else NS_PER_SECOND * 60.0 / revolution_ns

    return IntervalReport(
        pulses=len(intervals),
        clusters=clusters,
        separations=tuple(_separations(clusters, groups)),
        outliers=outliers,
        rpm=rpm,
        base_ns=centres[0],
    )


def analyse_capture(capture: FluxCapture) -> CaptureReport:
    return CaptureReport(
        tracks=tuple(
            TrackReport(
                index=track.index,
                revolutions=tuple(
                    analyse_intervals(
                        revolution.intervals,
                        revolution_ns=(
                            revolution.duration_ns
                            if revolution.complete and revolution.duration_ns
                            else None
                        ),
                    )
                    for revolution in track.revolutions
                ),
            )
            for track in capture.tracks
        )
    )
