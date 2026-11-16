from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from fdstoolkit.core.disk import Disk
from fdstoolkit.history.entries import disk_key
from fdstoolkit.history.logbook import Entry, history, logbook_path
from fdstoolkit.history.trend import Trend, trend_lines, trend_of

NEITHER: Final = "name a disk image or a drive label to show its history"
BOTH: Final = "name a disk image or a drive label, not both"
NO_IDENTITY: Final = "the image has no disk information, so the logbook cannot know it"


@dataclass(frozen=True, slots=True)
class Subject:
    disk: str | None
    drive: str | None
    title: str


def subject_for(disk: Disk | None, drive: str | None) -> Subject:
    if disk is None and not drive:
        raise ValueError(NEITHER)
    if disk is not None and drive:
        raise ValueError(BOTH)
    if disk is None:
        return Subject(disk=None, drive=drive, title=f"drive {drive}")
    key = disk_key(disk)
    if key is None:
        raise ValueError(NO_IDENTITY)
    return Subject(disk=key.id, drive=None, title=f"{key.id} {key.title}")


def look_up(subject: Subject) -> Trend:
    return trend_of(history(logbook_path(), disk=subject.disk, drive=subject.drive))


def _row(entry: Entry) -> dict[str, object]:
    return {
        "recorded": entry.recorded,
        "kind": entry.kind.value,
        "grade": entry.grade,
        "title": entry.title,
        "drive": entry.drive,
        "weak": [list(pair) for pair in entry.weak],
    }


def log_payload(subject: Subject, trend: Trend) -> dict[str, object]:
    return {
        "subject": subject.title,
        "entries": [_row(entry) for entry in trend.entries],
        "weakened": [list(pair) for pair in trend.weakened],
        "settled": [list(pair) for pair in trend.settled],
        "since": None if trend.since is None else trend.since.recorded,
        "lines": list(trend_lines(trend)),
    }
