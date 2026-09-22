from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from fdstoolkit.drive.spec import NOMINAL_BIT_RATE_HZ

HEALTHY_WIDTH: Final = 0.12
POOR_WIDTH: Final = 0.01


@dataclass(frozen=True, slots=True)
class Setting:
    label: str
    bit_rate_hz: float
    margin: float
    errors: int

    @property
    def clean(self) -> bool:
        return self.errors == 0


@dataclass(frozen=True, slots=True)
class Bracket:
    settings: tuple[Setting, ...]

    @property
    def ordered(self) -> tuple[Setting, ...]:
        return tuple(sorted(self.settings, key=lambda item: item.bit_rate_hz))

    @property
    def clean(self) -> tuple[Setting, ...]:
        return tuple(item for item in self.ordered if item.clean)

    @property
    def window(self) -> tuple[float, float] | None:
        readable = self.clean
        if not readable:
            return None
        return (readable[0].bit_rate_hz, readable[-1].bit_rate_hz)

    @property
    def centre(self) -> float | None:
        span = self.window
        if span is None:
            return None
        return (span[0] + span[1]) / 2

    @property
    def width(self) -> float:
        span = self.window
        if span is None:
            return 0.0
        return (span[1] - span[0]) / NOMINAL_BIT_RATE_HZ

    @property
    def usable(self) -> bool:
        return self.window is not None

    @property
    def health(self) -> float:
        if self.width >= HEALTHY_WIDTH:
            return 1.0
        if self.width <= POOR_WIDTH:
            return 0.0
        return (self.width - POOR_WIDTH) / (HEALTHY_WIDTH - POOR_WIDTH)

    @property
    def best(self) -> Setting | None:
        middle = self.centre
        if middle is None:
            return None
        return min(self.clean, key=lambda item: abs(item.bit_rate_hz - middle))

    def render(self) -> str:
        span = self.window
        best = self.best
        if span is None or best is None:
            return "no setting read clean, so the window cannot be found"
        return (
            f"window {span[0] / 1000:.2f} to {span[1] / 1000:.2f} kbit/s "
            f"({self.width:.1%} wide), centre {(span[0] + span[1]) / 2000:.2f} kbit/s, "
            f"nearest setting {best.label}"
        )


def bracket_of(settings: Sequence[Setting]) -> Bracket:
    if not settings:
        message = "a sweep needs at least one setting"
        raise ValueError(message)
    return Bracket(settings=tuple(settings))
