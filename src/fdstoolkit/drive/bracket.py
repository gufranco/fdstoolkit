from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final


class Heading(StrEnum):
    ONWARD = "onward"
    BACK = "back"


class Phase(StrEnum):
    SEEKING = "seeking a position that reads"
    FIRST_EDGE = "turning until it stops reading"
    SECOND_EDGE = "turning back until it stops reading again"
    DONE = "done"


INSTRUCTIONS: Final[dict[Heading, str]] = {
    Heading.ONWARD: (
        "turn the adjustment one small step, the same way every time, then confirm to read again"
    ),
    Heading.BACK: (
        "turn the adjustment one small step the other way, the same size as before, "
        "then confirm to read again"
    ),
}

STEP: Final[dict[Heading, int]] = {Heading.ONWARD: 1, Heading.BACK: -1}


@dataclass(frozen=True, slots=True)
class Bracket:
    phase: Phase = Phase.SEEKING
    heading: Heading = Heading.ONWARD
    position: int = 0
    first_edge: int | None = None
    second_edge: int | None = None

    @property
    def instruction(self) -> str:
        return INSTRUCTIONS[self.heading]

    @property
    def done(self) -> bool:
        return self.phase is Phase.DONE

    @property
    def width(self) -> int:
        if self.first_edge is None or self.second_edge is None:
            return 0
        return self.first_edge - self.second_edge - 1

    @property
    def steps_to_middle(self) -> int:
        if self.first_edge is None or self.second_edge is None:
            return 0
        return (self.first_edge - self.second_edge) // 2

    @property
    def verdict(self) -> str:
        if self.phase is Phase.SEEKING:
            return "no read was clean yet: keep turning the same way, or start again the other way"
        if self.phase is Phase.FIRST_EDGE:
            return "it still reads: keep turning the same way until it stops"
        if self.phase is Phase.SECOND_EDGE:
            return "it stopped reading on one side: coming back to find the other side"
        return (
            f"it reads across {self.width} step(s): turn {self.steps_to_middle} step(s) "
            "the way you first turned, to sit in the middle of that range"
        )

    def after(self, *, clean: bool) -> Bracket:
        if self.phase is Phase.DONE:
            return self
        if self.phase is Phase.SEEKING and clean:
            return self._move(phase=Phase.FIRST_EDGE)
        if self.phase is Phase.FIRST_EDGE and not clean:
            return replace(
                self,
                first_edge=self.position,
                heading=Heading.BACK,
                phase=Phase.SECOND_EDGE,
                position=self.position + STEP[Heading.BACK],
            )
        if self.phase is Phase.SECOND_EDGE and not clean:
            return replace(self, second_edge=self.position, phase=Phase.DONE)
        return self._move(phase=self.phase)

    def _move(self, *, phase: Phase) -> Bracket:
        return replace(self, phase=phase, position=self.position + STEP[self.heading])
