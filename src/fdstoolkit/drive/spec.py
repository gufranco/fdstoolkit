from __future__ import annotations

from dataclasses import dataclass
from typing import Final

NS_PER_SECOND: Final = 1_000_000_000

NOMINAL_BIT_RATE_HZ: Final = 96_400
ACCEPT_TOLERANCE: Final = 0.10
FINE_TOLERANCE: Final = 0.01

CAPTURE_CLOCK_HZ: Final = 6_000_000

CPU_CLOCK_HZ: Final = 1_789_772.5
CYCLES_PER_BYTE: Final = 148
BITS_PER_BYTE: Final = 8

HEAD_GAP_MM: Final = 10.72
HEAD_GAP_TOLERANCE_MM: Final = 0.05
HEAD_GAP_USABLE_MM: Final = 0.11
HEAD_TURN_MM: Final = 0.05
TURNS_PER_STEP: Final = 0.125
HEAD_RADIUS_MM: Final = 35.5


@dataclass(frozen=True, slots=True)
class Band:
    low: float
    high: float
    centre: float

    @property
    def width(self) -> float:
        return self.high - self.low

    def holds(self, value: float) -> bool:
        return self.low <= value <= self.high

    def offset(self, value: float) -> float:
        half = self.width / 2
        if half <= 0:
            return 0.0
        return (value - self.centre) / half


def cell_from_bit_rate(bit_rate_hz: float) -> float:
    if bit_rate_hz <= 0:
        return 0.0
    return NS_PER_SECOND / bit_rate_hz


def bit_rate_from_cell(cell_ns: float) -> float:
    if cell_ns <= 0:
        return 0.0
    return NS_PER_SECOND / cell_ns


def counts_from_cell(cell_ns: float) -> float:
    return cell_ns * CAPTURE_CLOCK_HZ / NS_PER_SECOND


def _band(tolerance: float) -> Band:
    return Band(
        low=NOMINAL_BIT_RATE_HZ * (1 - tolerance),
        high=NOMINAL_BIT_RATE_HZ * (1 + tolerance),
        centre=float(NOMINAL_BIT_RATE_HZ),
    )


def accept_band() -> Band:
    return _band(ACCEPT_TOLERANCE)


def fine_band() -> Band:
    return _band(FINE_TOLERANCE)


def head_turns_for(millimetres: float) -> float:
    if not millimetres:
        return 0.0
    return millimetres / HEAD_TURN_MM * TURNS_PER_STEP
