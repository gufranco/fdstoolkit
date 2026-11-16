from __future__ import annotations

from collections.abc import Sequence

from fdstoolkit.hardware.recording import Arg, Event


class ReplayDivergedError(AssertionError):
    pass


class ReplayDevice:
    def __init__(self, events: Sequence[Event]) -> None:
        self._events = tuple(events)
        self._next = 0

    @property
    def exhausted(self) -> bool:
        return self._next == len(self._events)

    def open(self, vendor_id: int, product_id: int) -> None:
        self._answer("open", (vendor_id, product_id))

    def send_feature_report(self, data: bytes) -> int:
        return _number(self._answer("send_feature_report", (data.hex(),)))

    def get_feature_report(self, report_id: int, length: int) -> list[int]:
        answer = self._answer("get_feature_report", (report_id, length)).result
        if not isinstance(answer, str):
            message = f"the recorded answer to report {report_id:#04x} is not bytes"
            raise ReplayDivergedError(message)
        return list(bytes.fromhex(answer))

    def write(self, data: bytes) -> int:
        return _number(self._answer("write", (data.hex(),)))

    def close(self) -> None:
        self._answer("close", ())

    def _answer(self, call: str, args: tuple[Arg, ...]) -> Event:
        if self.exhausted:
            message = f"the driver called {call}{args} after the recording ended"
            raise ReplayDivergedError(message)
        event = self._events[self._next]
        if (event.call, event.args) != (call, args):
            message = (
                f"the recording holds {event.call}{event.args} next, "
                f"and the driver called {call}{args}"
            )
            raise ReplayDivergedError(message)
        self._next += 1
        if event.error is not None:
            raise OSError(event.error)
        return event


def _number(event: Event) -> int:
    if not isinstance(event.result, int):
        message = f"the recorded answer to {event.call} is not a number"
        raise ReplayDivergedError(message)
    return event.result
