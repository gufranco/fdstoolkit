from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fdstoolkit.drive.spec import (
    BITS_PER_BYTE,
    CPU_CLOCK_HZ,
    NOMINAL_BIT_RATE_HZ,
    NS_PER_SECOND,
    accept_band,
    bit_rate_from_cell,
    fine_band,
)


class Verdict(StrEnum):
    OUT_OF_SPEC = "out of spec"
    IN_SPEC = "in spec"
    FINE = "fine"


class Direction(StrEnum):
    FASTER = "faster"
    SLOWER = "slower"
    HOLD = "hold"


ADVICE: dict[Direction, str] = {
    Direction.FASTER: "the drive reads slow: raise the motor speed a little, then measure again",
    Direction.SLOWER: "the drive reads fast: lower the motor speed a little, then measure again",
    Direction.HOLD: "the speed is inside the fine band: leave the motor speed alone",
}


@dataclass(frozen=True, slots=True)
class SpeedReport:
    cell_ns: float

    @property
    def bit_rate_hz(self) -> float:
        return bit_rate_from_cell(self.cell_ns)

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
    def advice(self) -> str:
        return ADVICE[self.direction]

    def render(self) -> str:
        return (
            f"{self.bit_rate_hz / 1000:.2f} kbit/s, {self.error:+.2%} of nominal, "
            f"{self.verdict.value}\n{self.advice}"
        )


def from_cycles(cycles_per_byte: float) -> SpeedReport:
    if cycles_per_byte <= 0:
        message = "a cycle count between bytes is positive"
        raise ValueError(message)
    return SpeedReport(cell_ns=NS_PER_SECOND * cycles_per_byte / (CPU_CLOCK_HZ * BITS_PER_BYTE))
