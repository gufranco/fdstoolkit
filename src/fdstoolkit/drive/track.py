from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from fdstoolkit.codecs.raw import MAX_CLASS, unpack_detected
from fdstoolkit.drive.vote import parse_read
from fdstoolkit.drive.weak import KIND_NAMES, WeakBlock, weak_blocks

TRACK_BINS: Final = 160
KIND_WIDTH: Final = 12


@dataclass(frozen=True, slots=True)
class Bin:
    start: int
    end: int
    classes: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class TrackBlock:
    index: int
    kind: str
    start: int
    end: int
    weak: WeakBlock | None

    @property
    def label(self) -> str:
        if self.weak is None:
            return f"block {self.index}, {self.kind}: steady"
        return f"block {self.index}, {self.kind}: {_figures(self.weak)}"


@dataclass(frozen=True, slots=True)
class Track:
    side: int
    reads: int
    length: int
    bins: tuple[Bin, ...]
    blocks: tuple[TrackBlock, ...]

    @property
    def weak(self) -> tuple[TrackBlock, ...]:
        return tuple(block for block in self.blocks if block.weak is not None)


def _figures(weak: WeakBlock) -> str:
    lost = f", missing from {weak.missing} read(s)" if weak.missing else ""
    return (
        f"{weak.unstable} pulse(s) differ across {weak.reads} read(s), {weak.invalid} invalid{lost}"
    )


def _classes(chunk: bytes) -> tuple[int, int, int, int]:
    return (chunk.count(0), chunk.count(1), chunk.count(2), chunk.count(MAX_CLASS))


def _bins(values: bytes) -> tuple[Bin, ...]:
    size = max(1, -(-len(values) // TRACK_BINS))
    return tuple(
        Bin(
            start=start,
            end=min(start + size, len(values)),
            classes=_classes(values[start : start + size]),
        )
        for start in range(0, len(values), size)
    )


def track_of(captures: Sequence[bytes], side: int) -> Track:
    if not captures:
        message = f"the captures hold no read of side {side}"
        raise ValueError(message)
    reads = [parse_read(unpack_detected(packed)) for packed in captures]
    base = max(reads, key=lambda read: len(read.blocks))
    weak = {entry.block: entry for entry in weak_blocks(captures)}
    blocks = tuple(
        TrackBlock(
            index=index,
            kind=KIND_NAMES[block.kind],
            start=start,
            end=end,
            weak=weak.get(index),
        )
        for index, (block, (start, end)) in enumerate(zip(base.blocks, base.regions, strict=True))
    )
    return Track(
        side=side, reads=len(reads), length=len(base.values), bins=_bins(base.values), blocks=blocks
    )


def track_lines(track: Track) -> tuple[str, ...]:
    heading = (
        f"side {track.side}, {track.reads} read(s), {track.length} values, "
        f"{len(track.blocks)} blocks, {len(track.weak)} weak"
    )
    rows = tuple(
        f"block {block.index}  {block.kind.ljust(KIND_WIDTH)} {block.start}-{block.end}  "
        f"{'steady' if block.weak is None else _figures(block.weak)}"
        for block in track.blocks
    )
    return (heading, *rows)


def _block_row(block: TrackBlock) -> dict[str, object]:
    weak = block.weak
    return {
        "index": block.index,
        "kind": block.kind,
        "start": block.start,
        "end": block.end,
        "weak": weak is not None,
        "unstable": 0 if weak is None else weak.unstable,
        "invalid": 0 if weak is None else weak.invalid,
        "missing": 0 if weak is None else weak.missing,
        "label": block.label,
    }


def track_payload(track: Track) -> dict[str, object]:
    return {
        "headline": track_lines(track)[0],
        "side": track.side,
        "reads": track.reads,
        "length": track.length,
        "bins": [
            {"start": found.start, "end": found.end, "classes": list(found.classes)}
            for found in track.bins
        ],
        "blocks": [_block_row(block) for block in track.blocks],
    }
