from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import groupby
from operator import itemgetter
from typing import Final, Protocol

from fdstoolkit.build.calibration import matching_side
from fdstoolkit.codecs.raw import (
    decode_raw03,
    unpack_detected,
)
from fdstoolkit.core.bios import BIOS_ERRORS, REPAIR_HINTS
from fdstoolkit.core.disk import Side
from fdstoolkit.core.diskinfo import FIELDS_BY_NAME
from fdstoolkit.drive.bracket import Bracket
from fdstoolkit.drive.sampling import HeadReading, SideSample, SpeedReading, learn, measure
from fdstoolkit.drive.vote import Key

MAX_READS: Final = 200


SPREAD_READS: Final = 5


DEFAULT_READS: Final = 20


MARK_TOLERANCE: Final = 8


FIXED_SHARE: Final = 0.5


NOISY_READ: Final = (
    ". Most failing pulses fit no class at all, which points at electrical noise on the read "
    "line more than at speed. Noise moves between reads while a damaged or overwritten spot "
    "on the disk stays put, so a second read tells them apart. If the USB link reported no "
    "skipped packets, the FDSStick's "
    "author found that a series resistor of about 10k on the READ DATA pin, pin 9 of the "
    "FDSStick pinout, helps with read errors"
)


FIXED_SPOT: Final = (
    ". Most failing pulses fit no class at all and sit at the same places on every read, so "
    "they are on the disk rather than on the read line: a damaged, worn or overwritten spot. "
    "Write the side again from a good image; if it still fails at the same place, the surface "
    "is damaged. Judge the drive with another disk meanwhile"
)


RECOGNISED: Final = (
    "this is the fdstoolkit calibration disk, side {side}: every pulse is compared with "
    "what the disk holds, including blocks that never read clean"
)


SIDE_OFFSET: Final = FIELDS_BY_NAME["side"].offset


NOT_THIS_DRIVE: Final = (
    "judge the drive only with a disk it did not write: a factory disk, or one written "
    "by a drive you trust. A drive out of adjustment reads back its own writes, so "
    "those prove nothing"
)


class Mode(StrEnum):
    SPEED = "speed"
    HEAD = "head"


class Trend(StrEnum):
    FIRST = "first read"
    BETTER = "better than the last read"
    WORSE = "worse than the last read"
    SAME = "the same as the last read"


SPEED_ADVICE: Final[dict[SpeedReading, str]] = {
    SpeedReading.NOTHING: (
        "the drive found no block at all: it is far off speed, or the head or the spindle "
        "hub is out of position. Run calibrate head if the speed was never touched"
    ),
    SpeedReading.FAST: "pulses read short, so the drive runs fast: lower the motor speed a little",
    SpeedReading.SLOW: "pulses read long, so the drive runs slow: raise the motor speed a little",
    SpeedReading.ERRORS: (
        "blocks fail without pulses leaning short or long, which does not look like speed: "
        "clean the head, try another disk, or run calibrate head"
    ),
    SpeedReading.CLEAN: (
        "inside the tolerance the stick can see. It cannot see the last percent, so finish "
        "with a console speed test or a strobe at the disk table"
    ),
}


FINE_TURN: Final = (
    "Turn the head screw about 45 degrees, since a full turn moves the head about one track,"
)


HEAD_ADVICE: Final[dict[HeadReading, str]] = {
    HeadReading.NOTHING: (
        "no block was found: the head or the spindle hub is far out of position, or the "
        "speed is. Adjust in one direction, a quarter turn at a time"
    ),
    HeadReading.START: (
        "the first blocks are missing and the rest read: the head starts in the wrong place. "
        f"{FINE_TURN} and watch whether more of the start comes back"
    ),
    HeadReading.END: (
        "the side reads until near its end: the head runs out of travel. "
        f"{FINE_TURN} and watch whether the end comes back"
    ),
    HeadReading.SCATTERED: (
        "failures are spread across the side, which points at speed or at the disk rather "
        "than at position: run calibrate speed"
    ),
    HeadReading.CLEAN: (
        "the whole side reads. Repeat with two more factory disks, since a head can be set "
        "to suit one disk and miss another"
    ),
}


class RawReader(Protocol):
    def read_raw_side(self, *, what: str) -> bytes: ...


@dataclass(slots=True)
class Replay:
    captures: tuple[bytes, ...]
    reads: int = 0

    def read_raw_side(self, *, what: str) -> bytes:
        if self.reads >= len(self.captures):
            message = f"{what}: the captures hold {len(self.captures)} reads"
            raise ValueError(message)
        self.reads += 1
        return self.captures[self.reads - 1]


def trend(previous: SideSample | None, current: SideSample) -> Trend:
    if previous is None:
        return Trend.FIRST
    before = previous.score()
    after = current.score()
    if after > before:
        return Trend.BETTER
    if after < before:
        return Trend.WORSE
    return Trend.SAME


def _span(indices: Sequence[int]) -> str:
    if len(indices) == 1:
        return f"block {indices[0]}"
    if list(indices) == list(range(indices[0], indices[-1] + 1)):
        return f"blocks {indices[0]} to {indices[-1]}"
    return "blocks " + ", ".join(str(index) for index in indices)


def verdict(mode: Mode, current: SideSample) -> str:
    return current.speed.value if mode is Mode.SPEED else current.head.value


def advice(mode: Mode, current: SideSample) -> str:
    return SPEED_ADVICE[current.speed] if mode is Mode.SPEED else HEAD_ADVICE[current.head]


def describe(mode: Mode, number: int, current: SideSample, change: Trend) -> str:
    parts = [f"read {number}: {current.read} of {current.expected} blocks"]
    if mode is Mode.HEAD and current.missing and current.read:
        parts.append(f"{_span(current.missing)} not read")
    if current.referenced:
        parts.append(f"{current.short} pulses short, {current.long} long")
    parts.append(f"{current.invalid} invalid")
    if current.lead_in is not None:
        parts.append(f"lead-in {current.lead_in} bits")
    error = current.console_error
    if error is not None:
        hint = REPAIR_HINTS.get(error)
        parts.append(f"console error {error:02X}, {BIOS_ERRORS[error]}")
        parts.extend([hint] if hint else [])
    return f"{', '.join(parts)}: {verdict(mode, current)}, {change.value}"


@dataclass(frozen=True, slots=True)
class Calibration:
    mode: Mode
    samples: tuple[SideSample, ...]
    bracket: Bracket | None = None

    @property
    def last(self) -> SideSample | None:
        return self.samples[-1] if self.samples else None

    @property
    def clean(self) -> bool:
        last = self.last
        if last is None:
            return False
        return _clean(self.mode, last)

    def rows(self) -> list[dict[str, object]]:
        return [
            {
                "read": sample.read,
                "expected": sample.expected,
                "missing": list(sample.missing),
                "short": sample.short,
                "long": sample.long,
                "invalid": sample.invalid,
                "lead_in": sample.lead_in,
                "verdict": verdict(self.mode, sample),
            }
            for sample in self.samples
        ]

    @property
    def headline(self) -> str:
        last = self.last
        if last is None:
            return "stopped before the first read"
        if self.bracket is not None:
            return self.bracket.verdict
        spread = self.spread
        counted = ", ".join(f"{count} {name}" for name, count in spread.items())
        window = (
            f"; the last {sum(spread.values())} reads: {counted}" if len(self.samples) > 1 else ""
        )
        noise = _noise_note(self.samples)
        return f"{verdict(self.mode, last)}: {advice(self.mode, last)}{window}{noise}"

    @property
    def spread(self) -> dict[str, int]:
        recent = Counter(verdict(self.mode, sample) for sample in self.samples[-SPREAD_READS:])
        return dict(recent.most_common())


def _noise_note(samples: Sequence[SideSample]) -> str:
    last = samples[-1]
    if not last.noisy:
        return ""
    earlier = next((sample for sample in reversed(samples[:-1]) if sample.noisy), None)
    if earlier is not None and _fixed_share(earlier.marks, last.marks) >= FIXED_SHARE:
        return FIXED_SPOT
    return NOISY_READ


def _fixed_share(earlier: Sequence[tuple[int, int]], current: Sequence[tuple[int, int]]) -> float:
    if not current:
        return 0.0
    offsets = {
        block: tuple(offset for _, offset in group)
        for block, group in groupby(sorted(earlier), key=itemgetter(0))
    }
    recurring = sum(1 for block, offset in current if _near(offsets.get(block, ()), offset))
    return recurring / len(current)


def _near(offsets: Sequence[int], offset: int) -> bool:
    position = bisect_left(offsets, offset - MARK_TOLERANCE)
    return position < len(offsets) and offsets[position] <= offset + MARK_TOLERANCE


def _clean(mode: Mode, current: SideSample) -> bool:
    if mode is Mode.SPEED:
        return current.speed is SpeedReading.CLEAN
    return current.head is HeadReading.CLEAN


def _quiet(message: str) -> None:
    del message


def _never() -> bool:
    return False


def _declined(ask: Callable[[str], bool] | None, state: Bracket | None, *, started: bool) -> bool:
    if ask is None or state is None or not started:
        return False
    return not ask(state.instruction)


@dataclass(frozen=True, slots=True)
class _Session:
    mode: Mode
    samples: tuple[SideSample, ...]
    known: Side | None
    learned: Mapping[Key, bytes]
    state: Bracket | None


def _recognised(decoded: Side, progress: Callable[[str], None]) -> Side | None:
    known = matching_side(decoded.blocks)
    if known is not None:
        progress(RECOGNISED.format(side=known.blocks[0].payload[SIDE_OFFSET]))
    return known


def _read_once(
    session: _Session, packed: bytes, number: int, progress: Callable[[str], None]
) -> _Session:
    values = unpack_detected(packed)
    decoded, _ = decode_raw03(values)
    known = session.known if session.known is not None else _recognised(decoded, progress)
    current = measure(values, decoded.blocks, known, session.learned)
    change = trend(session.samples[-1] if session.samples else None, current)
    progress(describe(session.mode, number, current, change))
    state = session.state
    return _Session(
        mode=session.mode,
        samples=(*session.samples, current),
        known=known,
        learned=learn(session.learned, decoded.blocks),
        state=None if state is None else state.after(clean=_clean(session.mode, current)),
    )


def _finished(
    session: _Session, stopped: Callable[[], bool], ask: Callable[[str], bool] | None
) -> bool:
    state = session.state
    if state is not None and state.done:
        return True
    return stopped() or _declined(ask, state, started=bool(session.samples))


def calibrate(
    reader: RawReader,
    *,
    mode: Mode,
    reads: int = DEFAULT_READS,
    reference: Side | None = None,
    progress: Callable[[str], None] = _quiet,
    stopped: Callable[[], bool] = _never,
    bracket: Callable[[str], bool] | None = None,
) -> Calibration:
    if not 1 <= reads <= MAX_READS:
        message = f"a calibration reads the side between 1 and {MAX_READS} times"
        raise ValueError(message)
    state = None if bracket is None else Bracket()
    session = _Session(mode=mode, samples=(), known=reference, learned={}, state=state)
    for number in range(1, reads + 1):
        if _finished(session, stopped, bracket):
            break
        try:
            packed = reader.read_raw_side(what=f"calibration read {number}")
        except KeyboardInterrupt:
            break
        session = _read_once(session, packed, number, progress)
    return Calibration(mode=mode, samples=session.samples, bracket=session.state)
