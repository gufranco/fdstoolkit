from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Final

from fdstoolkit.archive.store import DumpRecord

DAYS_PER_YEAR: Final = 365.25
STABLE_BAND: Final = 0.5
MIN_FOR_DIRECTION: Final = 2


class Direction(StrEnum):
    UNKNOWN = "unknown"
    STABLE = "stable"
    DEGRADING = "degrading"
    IMPROVING = "improving"


@dataclass(frozen=True, slots=True)
class Point:
    taken: date
    blocks_bad: int
    blocks_total: int
    confidence: float

    @property
    def bad_share(self) -> float:
        if not self.blocks_total:
            return 0.0
        return self.blocks_bad / self.blocks_total


@dataclass(frozen=True, slots=True)
class Trend:
    disk_id: str
    points: tuple[Point, ...]
    blocks_per_year: float
    years: float

    @property
    def direction(self) -> Direction:
        if len(self.points) < MIN_FOR_DIRECTION or self.years <= 0:
            return Direction.UNKNOWN
        if abs(self.blocks_per_year) < STABLE_BAND:
            return Direction.STABLE
        return Direction.DEGRADING if self.blocks_per_year > 0 else Direction.IMPROVING

    @property
    def years_remaining(self) -> float | None:
        if self.direction is not Direction.DEGRADING:
            return None
        last = self.points[-1]
        left = max(0, last.blocks_total - last.blocks_bad)
        return left / self.blocks_per_year

    def render(self) -> str:
        if self.direction is Direction.UNKNOWN:
            return f"{self.disk_id}: not enough history to say"
        body = f"{self.disk_id}: {self.direction.value}, {self.blocks_per_year:+.1f} blocks a year"
        if self.years_remaining is None:
            return body
        return f"{body}, unreadable in about {self.years_remaining:.0f} years"


def _parse(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        message = f"{value} is not a date in YYYY-MM-DD form"
        raise ValueError(message) from error


def trend_of(records: Sequence[DumpRecord]) -> Trend:
    if not records:
        message = "a trend needs at least one dump"
        raise ValueError(message)

    ordered = sorted(records, key=lambda record: _parse(record.taken))
    points = tuple(
        Point(
            taken=_parse(record.taken),
            blocks_bad=record.blocks_bad,
            blocks_total=record.blocks_total,
            confidence=record.confidence,
        )
        for record in ordered
    )

    span = (points[-1].taken - points[0].taken).days / DAYS_PER_YEAR
    rate = 0.0
    if len(points) > 1 and span > 0:
        rate = (points[-1].blocks_bad - points[0].blocks_bad) / span

    return Trend(
        disk_id=ordered[0].disk_id,
        points=points,
        blocks_per_year=rate,
        years=max(0.0, span),
    )
