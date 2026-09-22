from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

NS_PER_SECOND: Final = 1_000_000_000
NOMINAL_BIT_NS: Final = 10_400
SHORT_NS: Final = NOMINAL_BIT_NS
MEDIUM_NS: Final = NOMINAL_BIT_NS * 3 // 2
LONG_NS: Final = NOMINAL_BIT_NS * 2
NOMINAL_RPM: Final = 96.0
WHOLE_SHARE: Final = 0.90
MIN_TO_COMPARE: Final = 3
REVOLUTION_NS: Final = int(NS_PER_SECOND * 60 / NOMINAL_RPM)


class Source(StrEnum):
    SCP = "scp"
    KRYOFLUX = "kryoflux"
    HFE = "hfe"
    FDSSTICK = "fdsstick"
    SYNTHETIC = "synthetic"


@dataclass(frozen=True, slots=True)
class Revolution:
    intervals: tuple[int, ...]
    complete: bool = True

    @property
    def pulse_count(self) -> int:
        return len(self.intervals)

    @property
    def duration_ns(self) -> int:
        return sum(self.intervals)

    @property
    def rpm(self) -> float:
        if not self.duration_ns:
            return 0.0
        return NS_PER_SECOND * 60.0 / self.duration_ns


@dataclass(frozen=True, slots=True)
class FluxTrack:
    index: int
    revolutions: tuple[Revolution, ...]

    def __post_init__(self) -> None:
        if not self.revolutions:
            message = f"track {self.index} carries no revolution"
            raise ValueError(message)

    @property
    def revolution_count(self) -> int:
        return len(self.revolutions)

    def intervals(self, revolution: int = 0) -> tuple[int, ...]:
        if not 0 <= revolution < self.revolution_count:
            message = f"track {self.index} has no revolution {revolution}"
            raise ValueError(message)
        return self.revolutions[revolution].intervals

    @property
    def all_intervals(self) -> tuple[int, ...]:
        return tuple(value for revolution in self.revolutions for value in revolution.intervals)


@dataclass(frozen=True, slots=True)
class FluxCapture:
    source: Source
    tracks: tuple[FluxTrack, ...]
    sample_ns: float = 25.0
    quantised: bool = False

    def __post_init__(self) -> None:
        if not self.tracks:
            message = "a capture carries no track"
            raise ValueError(message)

    @property
    def track_count(self) -> int:
        return len(self.tracks)

    def track(self, index: int) -> FluxTrack:
        for candidate in self.tracks:
            if candidate.index == index:
                return candidate
        message = f"the capture has no track {index}"
        raise ValueError(message)

    @property
    def pulse_count(self) -> int:
        return sum(
            revolution.pulse_count for track in self.tracks for revolution in track.revolutions
        )


def flag_partial(revolutions: Sequence[Revolution]) -> tuple[Revolution, ...]:
    if len(revolutions) < MIN_TO_COMPARE:
        return tuple(revolutions)
    durations = sorted(item.duration_ns for item in revolutions)
    middle = durations[len(durations) // 2]
    if not middle:
        return tuple(revolutions)
    return tuple(
        Revolution(
            intervals=item.intervals,
            complete=item.complete and item.duration_ns >= middle * WHOLE_SHARE,
        )
        for item in revolutions
    )
