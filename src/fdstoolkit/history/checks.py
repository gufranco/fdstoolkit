from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fdstoolkit.core.disk import Disk
from fdstoolkit.hardware.session import DumpResult
from fdstoolkit.history.entries import DriveKey, Stamp, disk_key
from fdstoolkit.history.logbook import Entry, EntryKind

Pair = tuple[int, int]


@dataclass(frozen=True, slots=True)
class Drift:
    current: Entry
    since: Entry | None
    moved: tuple[Pair, ...]


def _differing(result: DumpResult, reference: Disk | None) -> set[Pair]:
    if reference is None:
        return set()
    return {
        (side.index, read.index)
        for side in result.sides
        if side.index < reference.side_count
        for read in side.blocks
        if read.index < len(reference.sides[side.index].blocks)
        and read.payload != reference.sides[side.index].blocks[read.index].payload
    }


def check_entry(stamp: Stamp, result: DumpResult, reference: Disk | None, drive: DriveKey) -> Entry:
    read = {
        (side.index, index)
        for side in result.sides
        for index in (*side.marginal_blocks, *side.failed_blocks)
    }
    weak = read | _differing(result, reference)
    key = disk_key(reference if reference is not None else result.as_disk())
    return Entry(
        run=stamp.run,
        recorded=stamp.recorded,
        kind=EntryKind.CHECK,
        disk=None if key is None else key.id,
        title="unidentified disk" if key is None else key.title,
        stick=drive.stick,
        drive=drive.drive,
        grade=result.grade.value,
        weak=tuple(sorted(weak)),
    )


def drift_of(earlier: Sequence[Entry], current: Entry) -> Drift:
    since = next(
        (
            entry
            for entry in reversed(earlier)
            if entry.kind is EntryKind.CHECK and entry.drive == current.drive
        ),
        None,
    )
    if since is None:
        return Drift(current=current, since=None, moved=())
    moved = tuple(sorted(set(current.weak) - set(since.weak)))
    return Drift(current=current, since=since, moved=moved)


def _when(entry: Entry) -> str:
    return entry.recorded.replace("T", " ")[:16]


def drift_lines(drift: Drift) -> tuple[str, ...]:
    if drift.since is None:
        weak = len(drift.current.weak)
        return (
            (
                f"first check of drive {drift.current.drive} logged with {weak} weak block(s); "
                "the next check compares against it"
            ),
        )
    when = _when(drift.since)
    if not drift.moved:
        return (f"the drive reads as it did at the check of {when}",)
    blocks = ", ".join(f"side {side} block {block}" for side, block in drift.moved)
    return (
        (
            f"the drive moved since the check of {when}: {len(drift.moved)} block(s) now weak, "
            f"{blocks}"
        ),
    )


def drift_payload(drift: Drift) -> dict[str, object]:
    return {
        "headline": drift_lines(drift)[0],
        "ok": not drift.moved,
        "grade": drift.current.grade,
        "weak": [list(pair) for pair in drift.current.weak],
        "moved": [list(pair) for pair in drift.moved],
        "since": None if drift.since is None else drift.since.recorded,
    }
