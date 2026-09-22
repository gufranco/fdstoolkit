from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.drive.speed import Direction, SpeedReport, Verdict, measure_speed
from fdstoolkit.drive.stability import Motion, StabilityReport, measure_stability

FINE_WOW: Final = 0.002
COARSE_WOW: Final = 0.02
FINE_DRIFT: Final = 0.005
COARSE_DRIFT: Final = 0.03
SPEED_WEIGHT: Final = 0.6
MOTION_WEIGHT: Final = 0.4


class Stage(StrEnum):
    COARSE = "coarse"
    FINE = "fine"


@dataclass(frozen=True, slots=True)
class Action:
    stage: Stage
    subject: str
    finding: str
    action: str
    gain: float

    def render(self) -> str:
        return f"[{self.stage.value}] {self.subject}: {self.finding}. {self.action}"


@dataclass(frozen=True, slots=True)
class Advice:
    speed: SpeedReport
    stability: StabilityReport
    actions: tuple[Action, ...]

    @property
    def settled(self) -> bool:
        return not self.actions

    @property
    def score(self) -> float:
        speed = max(0.0, 1.0 - abs(self.speed.error) / 0.10)
        return SPEED_WEIGHT * speed + MOTION_WEIGHT * self.stability.quality

    def render(self) -> str:
        head = f"{self.speed.render()}\n{self.stability.render()}\nscore {self.score:.0%}"
        if self.settled:
            return f"{head}\nsettled, nothing left to adjust"
        body = "\n".join(f"  {action.render()}" for action in self.actions)
        return f"{head}\n{body}"


def _speed_action(speed: SpeedReport) -> Action | None:
    if speed.verdict is Verdict.FINE:
        return None
    stage = Stage.COARSE if speed.verdict is Verdict.OUT_OF_SPEC else Stage.FINE
    target = (
        "outside the band the adapter tolerates"
        if stage is Stage.COARSE
        else "inside the band but off centre"
    )
    turn = "counter-clockwise" if speed.direction is Direction.FASTER else "clockwise"
    return Action(
        stage=stage,
        subject="motor speed",
        finding=f"{speed.bit_rate_hz / 1000:.2f} kbit/s, {speed.error:+.2%} of nominal, {target}",
        action=(
            f"turn the motor trimmer {turn} to run {speed.direction.value}, then measure again"
        ),
        gain=min(1.0, abs(speed.error) / 0.10),
    )


def _motion_action(motion: StabilityReport) -> Action | None:
    wow = motion.wow_flutter
    drift = abs(motion.drift)
    if wow <= FINE_WOW and drift <= FINE_DRIFT:
        return None

    stage = Stage.COARSE if wow >= COARSE_WOW or drift >= COARSE_DRIFT else Stage.FINE
    if motion.motion is Motion.DRIFTING:
        finding = f"speed drifts {motion.drift:+.2%} across the capture"
        action = "check the belt for slip and the motor for warming, then measure again"
    else:
        finding = f"wow and flutter {wow:.2%}, spread {motion.spread:.2%}"
        action = "replace or reseat the belt and check the spindle runs true, then measure again"
    return Action(
        stage=stage,
        subject="belt and spindle",
        finding=finding,
        action=action,
        gain=min(1.0, max(wow / COARSE_WOW, drift / COARSE_DRIFT)),
    )


def advise(intervals: Sequence[int]) -> Advice:
    if not intervals:
        message = "a capture with no interval cannot be advised on"
        raise ValueError(message)

    speed = measure_speed(intervals)
    motion = measure_stability(intervals)

    found = [item for item in (_speed_action(speed), _motion_action(motion)) if item is not None]
    found.sort(key=lambda item: (0 if item.stage is Stage.COARSE else 1, -item.gain))

    return Advice(speed=speed, stability=motion, actions=tuple(found))
