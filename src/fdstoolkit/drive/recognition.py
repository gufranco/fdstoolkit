from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fdstoolkit.codecs.raw import decode_raw03, unpack_detected
from fdstoolkit.drive.captures import Capture
from fdstoolkit.drive.sampling import Recognition, recognition


@dataclass(frozen=True, slots=True)
class ReadRate:
    side: int
    read: int
    recognition: Recognition

    def render(self) -> str:
        counted = self.recognition.counted
        if not counted:
            return f"side {self.side} read {self.read}: no pulse was read"
        return (
            f"side {self.side} read {self.read}: {self.recognition.rate:.2%} of {counted} "
            f"pulses fit a class, counted {self.recognition.span.value}"
        )


def read_rate(capture: Capture) -> ReadRate:
    values = unpack_detected(capture.data)
    side, _ = decode_raw03(values)
    found = recognition(values, side.blocks)
    return ReadRate(side=capture.side, read=capture.read, recognition=found)


def read_rates(captures: Sequence[Capture]) -> tuple[ReadRate, ...]:
    return tuple(read_rate(capture) for capture in captures)


def rate_lines(captures: Sequence[Capture]) -> tuple[str, ...]:
    return tuple(rate.render() for rate in read_rates(captures))
