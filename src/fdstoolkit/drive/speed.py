from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from fdstoolkit.drive.spec import (
    BITS_PER_BYTE,
    CPU_CLOCK_HZ,
    NOMINAL_BIT_RATE_HZ,
    NS_PER_SECOND,
    accept_band,
    bit_rate_from_cell,
    counts_from_cell,
    fine_band,
)
from fdstoolkit.flux.analysis import fit_family


class Verdict(StrEnum):
    OUT_OF_SPEC = "out of spec"
    IN_SPEC = "in spec"
    FINE = "fine"


class Direction(StrEnum):
    FASTER = "faster"
    SLOWER = "slower"
    HOLD = "hold"


@dataclass(frozen=True, slots=True)
class SpeedReport:
    cell_ns: float
    family: str

    @property
    def bit_rate_hz(self) -> float:
        return bit_rate_from_cell(self.cell_ns)

    @property
    def counts(self) -> float:
        return counts_from_cell(self.cell_ns)

    @property
    def cycles_per_byte(self) -> float:
        if self.bit_rate_hz <= 0:
            return 0.0
        return CPU_CLOCK_HZ * BITS_PER_BYTE / self.bit_rate_hz

    @property
    def error(self) -> float:
        return self.bit_rate_hz / NOMINAL_BIT_RATE_HZ - 1.0

    @property
    def verdict(self) -> Verdict:
        rate = self.bit_rate_hz
        if not accept_band().holds(rate):
            return Verdict.OUT_OF_SPEC
        if fine_band().holds(rate):
            return Verdict.FINE
        return Verdict.IN_SPEC

    @property
    def direction(self) -> Direction:
        if self.verdict is Verdict.FINE:
            return Direction.HOLD
        return Direction.SLOWER if self.error > 0 else Direction.FASTER

    @property
    def headroom(self) -> float:
        return max(0.0, 1.0 - abs(accept_band().offset(self.bit_rate_hz)))

    def render(self) -> str:
        body = (
            f"{self.bit_rate_hz / 1000:.2f} kbit/s, cell {self.cell_ns:.0f} ns "
            f"({self.counts:.1f} counts), {self.error:+.2%} of nominal, {self.verdict.value}"
        )
        if self.direction is Direction.HOLD:
            return f"{body}, hold"
        return f"{body}, run {self.direction.value}"


def measure_speed(intervals: Sequence[int]) -> SpeedReport:
    if not intervals:
        message = "a capture with no interval has no speed"
        raise ValueError(message)
    base, _, family = fit_family(intervals)
    return SpeedReport(cell_ns=base, family=family)


def from_cycles(cycles_per_byte: float) -> SpeedReport:
    if cycles_per_byte <= 0:
        message = "a cycle count between bytes is positive"
        raise ValueError(message)
    cell = NS_PER_SECOND * cycles_per_byte / (CPU_CLOCK_HZ * BITS_PER_BYTE)
    return SpeedReport(cell_ns=cell, family="console")
