from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from fdstoolkit.codecs.raw import MAX_CLASS, unpack_raw03
from fdstoolkit.core.blocks import BlockKind
from fdstoolkit.drive.captures import Bundle
from fdstoolkit.drive.vote import (
    Read,
    alignment,
    locate,
    occurrence_of,
    parse_read,
    shared_length,
    window_of,
)

KIND_NAMES: Final[dict[BlockKind, str]] = {
    BlockKind.DISK_INFO: "disk info",
    BlockKind.FILE_AMOUNT: "file amount",
    BlockKind.FILE_HEADER: "file header",
    BlockKind.FILE_DATA: "file data",
}


@dataclass(frozen=True, slots=True)
class WeakBlock:
    block: int
    kind: str
    unstable: int
    invalid: int
    reads: int
    missing: int

    @property
    def weight(self) -> int:
        return self.unstable + self.invalid + self.missing

    def render(self) -> str:
        lost = f", missing from {self.missing} read(s)" if self.missing else ""
        return (
            f"block {self.block} ({self.kind}): {self.unstable} pulse(s) differ across "
            f"{self.reads} read(s), {self.invalid} invalid{lost}"
        )


def _unstable(windows: Sequence[bytes]) -> int:
    base = next(window for window in windows if len(window) == shared_length(windows))
    aligned = [alignment(base, window) for window in windows if window is not base]
    differing = sum(
        1
        for position, own in enumerate(base)
        if any(column[position] != own for column, _ in aligned)
    )
    return differing + sum(skipped for _, skipped in aligned)


def _weak(base: Read, slot: int, reads: Sequence[Read]) -> WeakBlock:
    identity, occurrence = occurrence_of(base, slot)
    windows = [
        window_of(read, position)
        for read in reads
        if (position := locate(read, identity, occurrence)) is not None
    ]
    return WeakBlock(
        block=slot,
        kind=KIND_NAMES[base.blocks[slot].kind],
        unstable=_unstable(windows),
        invalid=sum(window[: shared_length(windows)].count(MAX_CLASS) for window in windows),
        reads=len(windows),
        missing=len(reads) - len(windows),
    )


def weak_blocks(captures: Sequence[bytes]) -> tuple[WeakBlock, ...]:
    reads = [parse_read(unpack_raw03(packed)) for packed in captures]
    if not reads:
        return ()
    base = max(reads, key=lambda read: len(read.blocks))
    found = [_weak(base, slot, reads) for slot in range(len(base.blocks))]
    weak = [entry for entry in found if entry.weight]
    return tuple(sorted(weak, key=lambda entry: (-entry.missing, -entry.weight, entry.block)))


def bundle_weak_blocks(bundle: Bundle) -> tuple[tuple[int, WeakBlock], ...]:
    return tuple(
        (side, entry) for side in bundle.sides for entry in weak_blocks(bundle.of_side(side))
    )
