from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from statistics import fmean, pstdev
from typing import Final, Protocol

from fdstoolkit.codecs.raw import (
    NOMINAL_SHORT,
    decode_raw03,
    pack_raw03,
    quantise,
    unpack_raw03,
)
from fdstoolkit.drive.align import good_block
from fdstoolkit.hardware.ports import HardwareFaultError

NORMAL_MODE: Final = 0x00
PROBE_MODES: Final = (0x02, 0x03, 0x04, 0x05, 0x06, 0x07)
SMALLEST_COUNT: Final = 16
ZERO_SHARE: Final = 0.01
PEAK_WINDOW: Final = 2
PEAK_SHARE: Final = 0.02
COUNT_RANGE: Final = 256
CLASS_NAMES: Final = ("short", "medium", "long")
PERCENT: Final = 100

TIMING_OFF: Final = (
    "warning: timing is off, so every read is judged from pulse classes alone. Run the "
    "probe once to learn whether this firmware can send pulse timing, then calibrate with "
    "the timing mode it finds"
)
REPLAY_HAS_NO_TIMING: Final = (
    "warning: saved captures hold pulse classes, so a timing mode shows nothing when replaying them"
)
PROBE_WARNING: Final = (
    "the probe starts reads with modes this firmware does not document, and nothing shows "
    "that a disk's write-protect tab stops an FDSStick from writing. Put a scratch disk in the "
    "drive, such as the calibration disk, never one you want to keep. The probe reads the side "
    "before and after every mode and stops if the disk changed"
)
NO_TIMING: Final = (
    "no mode tried returned pulse timing, so this firmware sends pulse classes only. "
    "calibrate keeps working from classes, but cannot show how long each pulse was or "
    "how widely the pulses spread"
)


class Nature(StrEnum):
    TIMING = "pulse timing"
    UNDECODED = "what looks like pulse timing, though no block decoded from it"
    CLASSES = "pulse classes only"
    NOTHING = "no data"
    FAULT = "a fault"


class ModeReader(Protocol):
    def read_raw_side(self, *, what: str, mode: int) -> bytes: ...


def _short_nominal(counts: bytes) -> int | None:
    usable = Counter(count for count in counts if count >= SMALLEST_COUNT)
    total = sum(usable.values())
    smoothed = [
        sum(usable[value + step] for step in range(-PEAK_WINDOW, PEAK_WINDOW + 1))
        for value in range(COUNT_RANGE)
    ]
    peaks = [
        value
        for value in range(SMALLEST_COUNT, COUNT_RANGE - 1)
        if smoothed[value] >= smoothed[value - 1]
        and smoothed[value] > smoothed[value + 1]
        and smoothed[value] >= total * PEAK_SHARE
    ]
    return peaks[0] if peaks else None


def _scale(counts: bytes) -> float:
    nominal = _short_nominal(counts)
    return nominal / NOMINAL_SHORT if nominal else 1.0


def classify(data: bytes) -> Nature:
    if not data:
        return Nature.NOTHING
    if data.count(0) > len(data) * ZERO_SHARE or _short_nominal(data) is None:
        return Nature.CLASSES
    side, _ = decode_raw03(quantise(data, _scale(data)))
    return Nature.TIMING if any(good_block(block) for block in side.blocks) else Nature.UNDECODED


@dataclass(frozen=True, slots=True)
class Timing:
    means: tuple[float, float, float]
    spreads: tuple[float, float, float]

    @property
    def spread_percent(self) -> float:
        shares = [
            spread / mean for mean, spread in zip(self.means, self.spreads, strict=True) if mean
        ]
        return fmean(shares) * PERCENT if shares else 0.0

    def render(self) -> str:
        classes = ", ".join(
            f"{name} {mean:.1f}±{spread:.1f}"
            for name, mean, spread in zip(CLASS_NAMES, self.means, self.spreads, strict=True)
        )
        return f"timing: {classes} counts, spread {self.spread_percent:.1f}%, smaller is better"


def measure_timing(counts: bytes) -> Timing:
    classes = quantise(counts, _scale(counts))
    groups = [
        [count for count, kind in zip(counts, classes, strict=True) if kind == index]
        for index in range(3)
    ]
    means = tuple(fmean(group) if group else 0.0 for group in groups)
    spreads = tuple(pstdev(group) if len(group) > 1 else 0.0 for group in groups)
    return Timing(
        means=(means[0], means[1], means[2]), spreads=(spreads[0], spreads[1], spreads[2])
    )


@dataclass(frozen=True, slots=True)
class ProbeResult:
    mode: int
    nature: Nature
    detail: str = ""

    def render(self) -> str:
        detail = f": {self.detail}" if self.detail else ""
        return f"mode {self.mode:#04x}: {self.nature.value}{detail}"


@dataclass(frozen=True, slots=True)
class Probe:
    results: tuple[ProbeResult, ...]
    changed_by: int | None = None

    @property
    def timing_mode(self) -> int | None:
        return next(
            (result.mode for result in self.results if result.nature is Nature.TIMING), None
        )

    @property
    def verdict(self) -> str:
        if self.changed_by is not None:
            return (
                f"mode {self.changed_by:#04x} changed the disk, so the probe stopped. The disk no "
                "longer holds what it held before; never use this mode"
            )
        found = self.timing_mode
        if found is not None:
            return (
                f"mode {found:#04x} returns pulse timing: calibrate with timing mode {found}, "
                f"--timing-mode {found} on the command line"
            )
        fault = next((result for result in self.results if result.nature is Nature.FAULT), None)
        if fault is not None:
            return f"the probe stopped on a fault before it found pulse timing: {fault.detail}"
        return NO_TIMING


def _payloads(packed: bytes) -> tuple[set[bytes], set[bytes]]:
    side, _ = decode_raw03(unpack_raw03(packed))
    every = {block.payload for block in side.blocks}
    return every, {block.payload for block in side.blocks if good_block(block)}


def _changed(before: bytes, after: bytes) -> bool:
    known, clean = _payloads(before)
    _, now = _payloads(after)
    return bool(now - known) or (bool(clean) and not now)


def _quiet(message: str) -> None:
    del message


def probe(
    reader: ModeReader,
    *,
    modes: Sequence[int] = PROBE_MODES,
    progress: Callable[[str], None] = _quiet,
) -> Probe:
    baseline = reader.read_raw_side(what="probe: the side as it reads normally", mode=NORMAL_MODE)
    results: list[ProbeResult] = []
    for mode in modes:
        try:
            data = reader.read_raw_side(what=f"probe: mode {mode:#04x}", mode=mode)
            after = reader.read_raw_side(what="probe: checking the disk", mode=NORMAL_MODE)
        except HardwareFaultError as fault:
            results.append(ProbeResult(mode=mode, nature=Nature.FAULT, detail=str(fault)))
            progress(results[-1].render())
            break
        results.append(ProbeResult(mode=mode, nature=classify(data)))
        progress(results[-1].render())
        if _changed(baseline, after):
            return Probe(results=tuple(results), changed_by=mode)
        if results[-1].nature is Nature.TIMING:
            break
    return Probe(results=tuple(results))


def _no_timings() -> list[Timing]:
    return []


@dataclass(slots=True)
class TimingReader:
    reader: ModeReader
    mode: int
    note: Callable[[str], None]
    timings: list[Timing] = field(default_factory=_no_timings)

    def read_raw_side(self, *, what: str) -> bytes:
        data = self.reader.read_raw_side(what=what, mode=self.mode)
        nature = classify(data)
        if nature not in {Nature.TIMING, Nature.UNDECODED}:
            self.note(
                f"{what}: mode {self.mode:#04x} returned {nature.value}, so this read is "
                "judged from classes and shows no timing"
            )
            return data
        timing = measure_timing(data)
        self.timings.append(timing)
        self.note(timing.render())
        return pack_raw03(quantise(data, _scale(data)))
