from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO, cast

from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError

if TYPE_CHECKING:
    from fdstoolkit.hardware.fdsstick import HidDevice

RECORD_ENV: Final = "FDSTOOLKIT_RECORD"
RECORDING_FORMAT: Final = "fdstoolkit-hid-recording"
RECORDING_VERSION: Final = 1
MS_PER_S: Final = 1000
MS_DIGITS: Final = 2

type Arg = int | str
type Outcome = int | str | None


class RecordingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Event:
    call: str
    args: tuple[Arg, ...]
    result: Outcome
    error: str | None
    elapsed_ms: float


def encode_event(event: Event) -> str:
    return json.dumps(
        {
            "call": event.call,
            "args": list(event.args),
            "result": event.result,
            "error": event.error,
            "ms": event.elapsed_ms,
        }
    )


def _header() -> dict[str, object]:
    return {"format": RECORDING_FORMAT, "version": RECORDING_VERSION}


def _checked_header(line: str) -> None:
    try:
        header = json.loads(line)
    except json.JSONDecodeError as error:
        message = f"the recording does not start with a {RECORDING_FORMAT} header"
        raise RecordingError(message) from error
    if header != _header():
        message = f"the recording header is {header}, and this version reads {_header()}"
        raise RecordingError(message)


def _arg(value: object, number: int) -> Arg:
    if isinstance(value, bool) or not isinstance(value, int | str):
        message = f"line {number} carries an argument that is neither a number nor text"
        raise RecordingError(message)
    return value


def _outcome(value: object, number: int) -> Outcome:
    if value is None:
        return None
    return _arg(value, number)


def _error(value: object, number: int) -> str | None:
    if value is not None and not isinstance(value, str):
        message = f"line {number} carries an error that is not text"
        raise RecordingError(message)
    return value


def _fields(line: str, number: int) -> tuple[object, object, object, object, float]:
    try:
        raw = json.loads(line)
        return raw["call"], raw["args"], raw["result"], raw["error"], float(raw["ms"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as seen:
        message = f"line {number} of the recording is not an event"
        raise RecordingError(message) from seen


def _event(line: str, number: int) -> Event:
    call, values, result, error, elapsed = _fields(line, number)
    if not isinstance(call, str) or not isinstance(values, list):
        message = f"line {number} carries no call name or no argument list"
        raise RecordingError(message)
    args = tuple(_arg(value, number) for value in cast("list[object]", values))
    return Event(call, args, _outcome(result, number), _error(error, number), elapsed)


def decode_events(lines: Iterable[str]) -> tuple[Event, ...]:
    rows = [(number, line) for number, line in enumerate(lines, start=1) if line.strip()]
    if not rows:
        message = "the recording is empty"
        raise RecordingError(message)
    _checked_header(rows[0][1])
    return tuple(_event(line, number) for number, line in rows[1:])


class RecordingDevice:
    def __init__(
        self,
        device: HidDevice,
        sink: TextIO,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._device = device
        self._sink = sink
        self._clock = clock
        self._last = clock()
        self._guard = threading.Lock()
        self._write(json.dumps(_header()))

    def open(self, vendor_id: int, product_id: int) -> None:
        try:
            self._call("open", (vendor_id, product_id), lambda: self._opened(vendor_id, product_id))
        except OSError:
            self._sink.close()
            raise

    def send_feature_report(self, data: bytes) -> int:
        return self._call(
            "send_feature_report", (data.hex(),), lambda: self._device.send_feature_report(data)
        )

    def get_feature_report(self, report_id: int, length: int) -> list[int]:
        answer = self._call(
            "get_feature_report",
            (report_id, length),
            lambda: bytes(self._device.get_feature_report(report_id, length)).hex(),
        )
        return list(bytes.fromhex(answer))

    def write(self, data: bytes) -> int:
        return self._call("write", (data.hex(),), lambda: self._device.write(data))

    def close(self) -> None:
        self._call("close", (), self._closed)
        self._sink.close()

    def _opened(self, vendor_id: int, product_id: int) -> None:
        self._device.open(vendor_id, product_id)

    def _closed(self) -> None:
        self._device.close()

    def _call[T: Outcome](self, call: str, args: tuple[Arg, ...], action: Callable[[], T]) -> T:
        try:
            result = action()
        except OSError as error:
            self._note(Event(call, args, None, str(error), self._elapsed()))
            raise
        self._note(Event(call, args, result, None, self._elapsed()))
        return result

    def _elapsed(self) -> float:
        now = self._clock()
        elapsed = round((now - self._last) * MS_PER_S, MS_DIGITS)
        self._last = now
        return elapsed

    def _note(self, event: Event) -> None:
        if self._sink.closed:
            return
        self._write(encode_event(event))

    def _write(self, line: str) -> None:
        with self._guard:
            self._sink.write(line + "\n")
            self._sink.flush()


def session_path(folder: Path) -> Path:
    return folder / f"session-{time.time_ns()}.jsonl"


def recorded(device: HidDevice) -> HidDevice:
    folder = os.environ.get(RECORD_ENV)
    if not folder:
        return device
    target = Path(folder)
    try:
        target.mkdir(parents=True, exist_ok=True)
        sink = session_path(target).open("x", encoding="utf-8")
    except OSError as error:
        message = (
            f"{RECORD_ENV} names {target}, which cannot hold a recording ({error}). "
            f"Point it at a folder you can write to, or unset it"
        )
        raise HardwareFaultError(message, kind=FaultKind.LINK) from error
    return RecordingDevice(device, sink)
