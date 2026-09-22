from __future__ import annotations

import time
from collections.abc import Callable

from fdstk.hardware.ports import FaultKind, HardwareFaultError


class DeadlineExceededError(HardwareFaultError):
    def __init__(self, message: str) -> None:
        super().__init__(message, kind=FaultKind.TIMEOUT)


class Deadline:
    def __init__(self, *, seconds: float, now: Callable[[], float] = time.monotonic) -> None:
        if seconds <= 0:
            message = f"a deadline is a positive number of seconds, got {seconds}"
            raise ValueError(message)
        self._seconds = seconds
        self._now = now
        self._started = now()

    @property
    def seconds(self) -> float:
        return self._seconds

    @property
    def elapsed(self) -> float:
        return self._now() - self._started

    @property
    def remaining(self) -> float:
        return max(self._seconds - self.elapsed, 0.0)

    @property
    def expired(self) -> bool:
        return self.elapsed >= self._seconds


def guard[T](deadline: Deadline, what: str, call: Callable[[], T]) -> T:
    result = call()
    if deadline.expired:
        message = (
            f"{what} did not finish within {deadline.seconds} seconds, "
            "so the drive is treated as stalled rather than slow"
        )
        raise DeadlineExceededError(message)
    return result
