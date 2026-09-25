from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol

from fdstoolkit.codecs.raw import (
    GAP_VALUE,
    MAX_CLASS,
    MIN_GAP_VALUES,
    SYNC_MARK,
    block_starts,
    decode_raw03,
    encode_era_b,
    unpack_raw03,
)
from fdstoolkit.core.bios import BIOS_ERRORS
from fdstoolkit.core.blocks import BlockKind
from fdstoolkit.core.crc import block_crc, encode_crc
from fdstoolkit.core.disk import Side
from fdstoolkit.drive.align import align_blocks, good_block
from fdstoolkit.drive.bracket import Bracket

MAX_READS: Final = 200
DEFAULT_READS: Final = 20
BIAS_PULSES: Final = 16
BIAS_SHARE: Final = 0.75
BLOCK_EXPECTED: Final = 0x21
CRC_FAILED: Final = 0x27

NOT_THIS_DRIVE: Final = (
    "judge the drive only with a disk it did not write: a factory disk, or one written "
    "by a drive you trust. A drive out of adjustment reads back its own writes, so "
    "those prove nothing"
)


class Mode(StrEnum):
    SPEED = "speed"
    HEAD = "head"


class SpeedReading(StrEnum):
    NOTHING = "nothing read"
    FAST = "reads fast"
    SLOW = "reads slow"
    ERRORS = "errors with no speed bias"
    CLEAN = "reads clean"


class HeadReading(StrEnum):
    NOTHING = "nothing read"
    START = "the start of the side is not read"
    END = "the end of the side is not read"
    SCATTERED = "errors across the side"
    CLEAN = "reads clean"


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

HEAD_ADVICE: Final[dict[HeadReading, str]] = {
    HeadReading.NOTHING: (
        "no block was found: the head or the spindle hub is far out of position, or the "
        "speed is. Adjust in one direction, a quarter turn at a time"
    ),
    HeadReading.START: (
        "the first blocks are missing and the rest read: the head starts in the wrong place. "
        "Adjust a quarter turn and watch whether more of the start comes back"
    ),
    HeadReading.END: (
        "the side reads until near its end: the head runs out of travel. Adjust a quarter "
        "turn and watch whether the end comes back"
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


@dataclass(frozen=True, slots=True)
class SideSample:
    blocks: tuple[bool, ...]
    short: int
    long: int
    invalid: int
    compared: int
    referenced: bool
    found: tuple[bool, ...] = ()
    kinds: tuple[BlockKind, ...] = ()

    @property
    def console_error(self) -> int | None:
        if not self.blocks:
            return BLOCK_EXPECTED + BlockKind.DISK_INFO
        missing = self.missing
        if not missing:
            return None
        first = missing[0]
        if not self.found or self.found[first]:
            return CRC_FAILED
        return BLOCK_EXPECTED + self.kinds[first]

    @property
    def read(self) -> int:
        return sum(self.blocks)

    @property
    def expected(self) -> int:
        return len(self.blocks)

    @property
    def missing(self) -> tuple[int, ...]:
        return tuple(index for index, good in enumerate(self.blocks) if not good)

    @property
    def speed(self) -> SpeedReading:
        if not self.read:
            return SpeedReading.NOTHING
        if not self.missing and not (self.short or self.long or self.invalid):
            return SpeedReading.CLEAN
        leaning = self.short + self.long
        if leaning >= BIAS_PULSES:
            if self.short >= leaning * BIAS_SHARE:
                return SpeedReading.FAST
            if self.long >= leaning * BIAS_SHARE:
                return SpeedReading.SLOW
        return SpeedReading.ERRORS

    @property
    def head(self) -> HeadReading:
        if not self.read:
            return HeadReading.NOTHING
        missing = self.missing
        if not missing:
            return HeadReading.CLEAN
        if missing == tuple(range(len(missing))):
            return HeadReading.START
        if missing == tuple(range(self.expected - len(missing), self.expected)):
            return HeadReading.END
        return HeadReading.SCATTERED

    def score(self) -> tuple[int, int]:
        return (self.read, -(self.short + self.long + self.invalid))


def _framed(payload: bytes) -> bytes:
    return bytes([SYNC_MARK]) + payload + encode_crc(block_crc(payload))


def _invalid(values: bytes) -> int:
    count = 0
    run = 0
    for value in values:
        if value == GAP_VALUE:
            run += 1
            continue
        if value == MAX_CLASS and run < MIN_GAP_VALUES:
            count += 1
        run = 0
    return count


def _leaning(actual: bytes, expected: bytes) -> tuple[int, int, int]:
    pairs = [
        (have, want) for have, want in zip(actual, expected, strict=False) if have != MAX_CLASS
    ]
    short = sum(1 for have, want in pairs if have < want)
    long = sum(1 for have, want in pairs if have > want)
    return short, long, len(pairs)


def sample(packed: bytes, reference: Side | None = None) -> SideSample:
    values = unpack_raw03(packed)
    decoded, _ = decode_raw03(values)
    invalid = _invalid(values)
    if reference is None:
        return SideSample(
            blocks=tuple(good_block(block) for block in decoded.blocks),
            short=0,
            long=0,
            invalid=invalid,
            compared=0,
            referenced=False,
            kinds=tuple(block.kind for block in decoded.blocks),
        )

    starts = block_starts(values)
    short = long = compared = 0
    placed = align_blocks(reference.blocks, decoded.blocks)
    blocks = [good for good, _ in placed]
    for wanted, (_, region) in zip(reference.blocks, placed, strict=True):
        if region is None:
            continue
        expected = encode_era_b(_framed(wanted.payload))
        start = starts[region]
        more_short, more_long, more = _leaning(values[start : start + len(expected)], expected)
        short += more_short
        long += more_long
        compared += more
    return SideSample(
        blocks=tuple(blocks),
        short=short,
        long=long,
        invalid=invalid,
        compared=compared,
        referenced=True,
        found=tuple(region is not None for _, region in placed),
        kinds=tuple(block.kind for block in reference.blocks),
    )


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
    error = current.console_error
    if error is not None:
        parts.append(f"console error {error:02X}, {BIOS_ERRORS[error]}")
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
        return f"{verdict(self.mode, last)}: {advice(self.mode, last)}"


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
    samples: list[SideSample] = []
    state = None if bracket is None else Bracket()
    for number in range(1, reads + 1):
        if stopped() or _declined(bracket, state, started=bool(samples)):
            break
        try:
            packed = reader.read_raw_side(what=f"calibration read {number}")
        except KeyboardInterrupt:
            break
        current = sample(packed, reference)
        change = trend(samples[-1] if samples else None, current)
        samples.append(current)
        progress(describe(mode, number, current, change))
        if state is not None:
            state = state.after(clean=_clean(mode, current))
            if state.done:
                break
    return Calibration(mode=mode, samples=tuple(samples), bracket=state)
