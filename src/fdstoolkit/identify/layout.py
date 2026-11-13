from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.codecs.raw import GAP_VALUE, block_regions, decode_raw03, unpack_detected
from fdstoolkit.core.disk import Disk
from fdstoolkit.drive.captures import Bundle
from fdstoolkit.drive.recovery import captures_of_another_disk

ENDING_VALUES: Final = 60
QUIET_PULSES: Final = 1
EVEN_GAP_BITS: Final = 4
STREAMED_SHARE: Final = 0.9
DUPLICATED_SHARE: Final = 0.1
MIN_ENDINGS: Final = 3
MIN_GAPS: Final = 2

FACTORY_MEASURED: Final = (
    "The only factory reference is one disk, whose two sides end every block in stray "
    "pulses, with gaps varying by 18 to 73 bits"
)


class Layout(StrEnum):
    DUPLICATED = "duplicated"
    STREAMED = "streamed"
    UNSETTLED = "unsettled"


@dataclass(frozen=True, slots=True)
class LayoutReading:
    reads: int
    endings: int
    quiet_endings: int
    gap_spread: int | None

    @property
    def layout(self) -> Layout:
        if self.endings < MIN_ENDINGS or self.gap_spread is None:
            return Layout.UNSETTLED
        share = self.quiet_endings / self.endings
        if share >= STREAMED_SHARE and self.gap_spread <= EVEN_GAP_BITS:
            return Layout.STREAMED
        if share <= DUPLICATED_SHARE and self.gap_spread > EVEN_GAP_BITS:
            return Layout.DUPLICATED
        return Layout.UNSETTLED

    def note(self) -> str:
        if self.gap_spread is None or self.endings < MIN_ENDINGS:
            return "the captures hold too few clean blocks to tell how the side was written"
        measured = (
            f"{self.quiet_endings} of {self.endings} blocks end with no stray pulses and "
            f"the gaps vary by {self.gap_spread} bits"
        )
        if self.layout is Layout.STREAMED:
            return (
                "the captures show a side written in one stream rather than by a duplicator: "
                f"{measured}. {FACTORY_MEASURED}"
            )
        if self.layout is Layout.DUPLICATED:
            return f"the captures show a duplicator's layout: {measured}"
        return f"the captures do not settle how the side was written: {measured}"


@dataclass(frozen=True, slots=True)
class _Marks:
    endings: tuple[int, ...]
    gaps: tuple[int, ...]


def _pulses_after(values: bytes, end: int) -> int:
    return sum(1 for value in values[end : end + ENDING_VALUES] if value != GAP_VALUE)


def _marks(packed: bytes) -> _Marks:
    values = unpack_detected(packed)
    side, _ = decode_raw03(values)
    regions = block_regions(values)
    clean = [block.stored_crc == block.computed_crc for block in side.blocks]
    endings = tuple(
        _pulses_after(values, end) for (_, end), ok in zip(regions, clean, strict=True) if ok
    )
    gaps = tuple(
        regions[index + 1][0] - regions[index][1]
        for index in range(len(regions) - 1)
        if clean[index] and clean[index + 1]
    )
    return _Marks(endings=endings, gaps=gaps)


def layout_of(captures: Sequence[bytes]) -> LayoutReading:
    marks = [_marks(packed) for packed in captures]
    endings = [count for mark in marks for count in mark.endings]
    spreads = [max(mark.gaps) - min(mark.gaps) for mark in marks if len(mark.gaps) >= MIN_GAPS]
    return LayoutReading(
        reads=len(captures),
        endings=len(endings),
        quiet_endings=sum(1 for count in endings if count <= QUIET_PULSES),
        gap_spread=max(spreads, default=None),
    )


def layouts_for(disk: Disk, bundle: Bundle) -> dict[int, LayoutReading]:
    foreign = captures_of_another_disk(disk, bundle)
    if foreign:
        raise ValueError(foreign)
    return {
        side: layout_of(bundle.of_side(side)) for side in bundle.sides if side < disk.side_count
    }
