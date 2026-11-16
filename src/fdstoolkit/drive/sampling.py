from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

from fdstoolkit.codecs.raw import (
    MAX_CLASS,
    block_pulses,
    block_regions,
    block_starts,
    decode_raw03,
    lead_in_bits,
    unpack_detected,
)
from fdstoolkit.core.bios import BLOCK_EXPECTED, CRC_FAILED
from fdstoolkit.core.blocks import Block, BlockKind, declared_blocks, expected_kind
from fdstoolkit.core.disk import Side
from fdstoolkit.drive.align import align_blocks, good_block
from fdstoolkit.drive.vote import Key, align_to, keyed

BIAS_PULSES: Final = 16


BIAS_SHARE: Final = 0.75


NOISY_PULSES: Final = 16


SPLICE_FIRST: Final = 16


SPLICE_VALUES: Final = 160


INVALID_PULSE: Final = re.compile(bytes([MAX_CLASS]))


NO_BLOCK: Final = -1


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


def lean(short: int, long: int) -> SpeedReading:
    leaning = short + long
    if leaning >= BIAS_PULSES:
        if short >= leaning * BIAS_SHARE:
            return SpeedReading.FAST
        if long >= leaning * BIAS_SHARE:
            return SpeedReading.SLOW
    return SpeedReading.ERRORS


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
    lead_in: int | None = None
    marks: tuple[tuple[int, int], ...] = ()

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
        return lean(self.short, self.long)

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

    @property
    def noisy(self) -> bool:
        return self.invalid >= NOISY_PULSES and self.invalid > self.short + self.long


def _marks(values: bytes, *, declared: int) -> tuple[tuple[int, int], ...]:
    regions = block_regions(values)
    pulses = tuple(found.start() for found in INVALID_PULSE.finditer(values))
    if not regions:
        return tuple((NO_BLOCK, index) for index in pulses)
    starts = [start for start, _ in regions]
    last = regions[declared - 1][1] if 0 < declared <= len(regions) else len(values)
    return tuple(
        _mark(index, starts)
        for index in pulses
        if starts[0] <= index < last and not _in_splice(index, regions)
    )


def _mark(index: int, starts: Sequence[int]) -> tuple[int, int]:
    block = bisect_right(starts, index) - 1
    return block, index - starts[block]


def _in_splice(index: int, regions: Sequence[tuple[int, int]]) -> bool:
    if any(start <= index < end for start, end in regions):
        return False
    return any(end + SPLICE_FIRST <= index < end + SPLICE_VALUES for _, end in regions)


def _decided_pulses(payload: bytes) -> bytes:
    return block_pulses(payload)[:-1]


def _leaning(actual: bytes, expected: bytes) -> tuple[int, int, int]:
    pairs = [
        (have, want)
        for have, want in zip(align_to(expected, actual), expected, strict=True)
        if have is not None and have != MAX_CLASS
    ]
    short = sum(1 for have, want in pairs if have < want)
    long = sum(1 for have, want in pairs if have > want)
    return short, long, len(pairs)


def learn(learned: Mapping[Key, bytes], blocks: Sequence[Block]) -> dict[Key, bytes]:
    fresh = {
        key: block.payload
        for key, block in zip(keyed(blocks), blocks, strict=True)
        if good_block(block) and key not in learned
    }
    return {**learned, **fresh}


def _against_learned(
    values: bytes, blocks: Sequence[Block], learned: Mapping[Key, bytes]
) -> tuple[int, int, int]:
    starts = block_starts(values)
    short = long = compared = 0
    for key, start in zip(keyed(blocks), starts, strict=False):
        payload = learned.get(key)
        if payload is None:
            continue
        expected = _decided_pulses(payload)
        more_short, more_long, more = _leaning(values[start : start + len(expected)], expected)
        short += more_short
        long += more_long
        compared += more
    return short, long, compared


def _declared_blocks(decoded: Sequence[Block]) -> int:
    for block in decoded:
        if block.kind is BlockKind.FILE_AMOUNT and good_block(block):
            return declared_blocks(block.payload)
    return 0


def sample(
    packed: bytes,
    reference: Side | None = None,
    learned: Mapping[Key, bytes] | None = None,
) -> SideSample:
    values = unpack_detected(packed)
    decoded, _ = decode_raw03(values)
    return measure(values, decoded.blocks, reference, learned or {})


def measure(
    values: bytes,
    decoded: Sequence[Block],
    reference: Side | None,
    learned: Mapping[Key, bytes],
) -> SideSample:
    measured = _measured(values, decoded, reference, learned)
    return replace(measured, lead_in=lead_in_bits(values) if decoded else None)


def _against_what_read(
    values: bytes,
    decoded: Sequence[Block],
    learned: Mapping[Key, bytes],
    marks: tuple[tuple[int, int], ...],
) -> SideSample:
    short, long, compared = _against_learned(values, decoded, learned)
    unread = max(_declared_blocks(decoded) - len(decoded), 0)
    missing = range(len(decoded), len(decoded) + unread)
    return SideSample(
        blocks=tuple(good_block(block) for block in decoded) + (False,) * unread,
        short=short,
        long=long,
        invalid=len(marks),
        marks=marks,
        compared=compared,
        referenced=compared > 0,
        found=(True,) * len(decoded) + (False,) * unread if unread else (),
        kinds=tuple(block.kind for block in decoded) + tuple(expected_kind(i) for i in missing),
    )


def _against_reference(
    values: bytes,
    decoded: Sequence[Block],
    reference: Side,
    marks: tuple[tuple[int, int], ...],
) -> SideSample:
    starts = block_starts(values)
    placed = align_blocks(reference.blocks, decoded)
    leanings = [
        _leaning(values[starts[region] : starts[region] + len(expected)], expected)
        for wanted, (_, region) in zip(reference.blocks, placed, strict=True)
        if region is not None
        for expected in (_decided_pulses(wanted.payload),)
    ]
    return SideSample(
        blocks=tuple(good for good, _ in placed),
        short=sum(short for short, _, _ in leanings),
        long=sum(long for _, long, _ in leanings),
        invalid=len(marks),
        marks=marks,
        compared=sum(compared for _, _, compared in leanings),
        referenced=True,
        found=tuple(region is not None for _, region in placed),
        kinds=tuple(block.kind for block in reference.blocks),
    )


def _measured(
    values: bytes,
    decoded: Sequence[Block],
    reference: Side | None,
    learned: Mapping[Key, bytes],
) -> SideSample:
    marks = _marks(values, declared=_declared_blocks(decoded))
    if reference is None:
        return _against_what_read(values, decoded, learned, marks)
    return _against_reference(values, decoded, reference, marks)
