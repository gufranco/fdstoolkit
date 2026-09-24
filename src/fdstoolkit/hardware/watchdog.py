from __future__ import annotations

import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Final

from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError

UNMEASURED_CEILING_S: Final = 20.0
MEASURED_MULTIPLE: Final = 3.0
MEASURED_FLOOR_S: Final = 2.0


HALF_WRITTEN: Final = ". The side may be half written, so dump the disk before using it"


class StallError(HardwareFaultError):
    def __init__(self, what: str, seconds: float, *, writing: bool = False) -> None:
        message = (
            f"{what} did not finish within {seconds:.1f} seconds, so the drive is treated "
            "as stalled and nothing was retried. Check that a disk is inserted, then the "
            "belt and the head"
        )
        super().__init__(message + (HALF_WRITTEN if writing else ""), kind=FaultKind.TIMEOUT)


class Watchdog:
    def __init__(
        self,
        *,
        on_stall: Callable[[], None],
        ceiling: float = UNMEASURED_CEILING_S,
        multiple: float = MEASURED_MULTIPLE,
        floor: float = MEASURED_FLOOR_S,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        if ceiling <= 0 or multiple <= 0 or floor <= 0:
            message = "a watchdog limit is a positive number of seconds"
            raise ValueError(message)
        self._on_stall = on_stall
        self._ceiling = ceiling
        self._multiple = multiple
        self._floor = floor
        self._now = now
        self._measured: float | None = None
        self._until: float | None = None
        self._what = ""
        self._writing = False
        self._armed = ceiling

    @property
    def measured(self) -> float | None:
        return self._measured

    @property
    def limit(self) -> float:
        if self._measured is None:
            return self._ceiling
        return min(self._ceiling, max(self._floor, self._measured * self._multiple))

    @contextmanager
    def side(self, what: str, *, writing: bool = False) -> Generator[None]:
        self._what = what
        self._writing = writing
        self._armed = self.limit
        started = self._now()
        self._until = started + self._armed
        try:
            yield
        finally:
            self._until = None
        self._measured = self._now() - started

    def call[T](self, action: Callable[[], T]) -> T:
        if self._until is None:
            return action()
        remaining = self._until - self._now()
        if remaining <= 0:
            raise self._stalled()

        values: list[T] = []
        errors: list[Exception] = []
        done = threading.Event()

        def work() -> None:
            try:
                values.append(action())
            except Exception as error:  # noqa: BLE001
                errors.append(error)
            finally:
                done.set()

        threading.Thread(target=work, name="fdstoolkit-usb", daemon=True).start()
        if not done.wait(remaining):
            raise self._stalled()
        if errors:
            raise errors[0]
        return values[0]

    def _stalled(self) -> StallError:
        threading.Thread(target=self._on_stall, name="fdstoolkit-close", daemon=True).start()
        return StallError(self._what, self._armed, writing=self._writing)
