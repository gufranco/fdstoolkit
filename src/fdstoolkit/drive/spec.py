from __future__ import annotations

from dataclasses import dataclass
from typing import Final

NS_PER_SECOND: Final = 1_000_000_000

NOMINAL_BIT_RATE_HZ: Final = 96_400
ACCEPT_TOLERANCE: Final = 0.10
FINE_TOLERANCE: Final = 0.01

CPU_CLOCK_HZ: Final = 1_789_772.5
BITS_PER_BYTE: Final = 8


@dataclass(frozen=True, slots=True)
class Band:
    low: float
    high: float

    def holds(self, value: float) -> bool:
        return self.low <= value <= self.high


def cell_from_bit_rate(bit_rate_hz: float) -> float:
    if bit_rate_hz <= 0:
        return 0.0
    return NS_PER_SECOND / bit_rate_hz


def bit_rate_from_cell(cell_ns: float) -> float:
    if cell_ns <= 0:
        return 0.0
    return NS_PER_SECOND / cell_ns


def _band(tolerance: float) -> Band:
    return Band(
        low=NOMINAL_BIT_RATE_HZ * (1 - tolerance),
        high=NOMINAL_BIT_RATE_HZ * (1 + tolerance),
    )


def accept_band() -> Band:
    return _band(ACCEPT_TOLERANCE)


def fine_band() -> Band:
    return _band(FINE_TOLERANCE)
