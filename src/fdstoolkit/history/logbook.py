from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, cast

LOGBOOK_ENV: Final = "FDSTOOLKIT_LOGBOOK"
DATA_ENV: Final = "XDG_DATA_HOME"
LOGBOOK_NAME: Final = "logbook.sqlite3"
BUSY_SECONDS: Final = 10.0

SCHEMA: Final = (
    (
        "CREATE TABLE IF NOT EXISTS entries ("
        "run TEXT PRIMARY KEY, recorded TEXT NOT NULL, kind TEXT NOT NULL, disk TEXT, "
        "title TEXT NOT NULL, stick TEXT, drive TEXT, grade TEXT NOT NULL, weak TEXT NOT NULL)"
    ),
    "CREATE INDEX IF NOT EXISTS entries_disk_recorded_idx ON entries (disk, recorded)",
    "CREATE INDEX IF NOT EXISTS entries_drive_recorded_idx ON entries (drive, recorded)",
)
INSERT: Final = (
    "INSERT OR IGNORE INTO entries "
    "(run, recorded, kind, disk, title, stick, drive, grade, weak) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
BY_DISK: Final = (
    "SELECT run, recorded, kind, disk, title, stick, drive, grade, weak "
    "FROM entries WHERE disk = ? ORDER BY recorded, run"
)
BY_DRIVE: Final = (
    "SELECT run, recorded, kind, disk, title, stick, drive, grade, weak "
    "FROM entries WHERE drive = ? ORDER BY recorded, run"
)

Row = tuple[str, str, str, str | None, str, str | None, str | None, str, str]


class EntryKind(StrEnum):
    DUMP = "dump"
    GRADE = "grade"
    CALIBRATION = "calibration"
    CHECK = "check"


class LogbookError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Entry:
    run: str
    recorded: str
    kind: EntryKind
    disk: str | None
    title: str
    stick: str | None
    drive: str | None
    grade: str
    weak: tuple[tuple[int, int], ...]


def logbook_path() -> Path:
    chosen = os.environ.get(LOGBOOK_ENV, "")
    if chosen:
        return Path(chosen)
    data = os.environ.get(DATA_ENV, "")
    root = Path(data) if data else Path.home() / ".local" / "share"
    return root / "fdstoolkit" / LOGBOOK_NAME


def _row(entry: Entry) -> tuple[object, ...]:
    weak = json.dumps([list(pair) for pair in entry.weak])
    return (
        entry.run,
        entry.recorded,
        entry.kind.value,
        entry.disk,
        entry.title,
        entry.stick,
        entry.drive,
        entry.grade,
        weak,
    )


def _entry(row: Row) -> Entry:
    run, recorded, kind, disk, title, stick, drive, grade, weak = row
    pairs = cast("list[list[int]]", json.loads(weak))
    return Entry(
        run=run,
        recorded=recorded,
        kind=EntryKind(kind),
        disk=disk,
        title=title,
        stick=stick,
        drive=drive,
        grade=grade,
        weak=tuple((side, block) for side, block in pairs),
    )


def append(path: Path, entry: Entry) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=BUSY_SECONDS)) as database, database:
            for statement in SCHEMA:
                database.execute(statement)
            database.execute(INSERT, _row(entry))
    except (sqlite3.Error, OSError) as error:
        message = f"could not write the logbook at {path}: {error}"
        raise LogbookError(message) from error


def _select(path: Path, query: str, key: str) -> Sequence[Row]:
    with closing(sqlite3.connect(path, timeout=BUSY_SECONDS)) as database:
        return cast("list[Row]", database.execute(query, (key,)).fetchall())


def history(path: Path, *, disk: str | None = None, drive: str | None = None) -> tuple[Entry, ...]:
    if not path.is_file():
        return ()
    query, key = (BY_DISK, disk) if disk is not None else (BY_DRIVE, drive or "")
    try:
        rows = _select(path, query, key)
    except sqlite3.Error as error:
        message = f"could not read the logbook at {path}: {error}"
        raise LogbookError(message) from error
    return tuple(_entry(row) for row in rows)


def record(entry: Entry) -> None:
    append(logbook_path(), entry)
