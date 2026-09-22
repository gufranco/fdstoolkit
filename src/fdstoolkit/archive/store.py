from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Final, Self

from fdstoolkit.core.disk import Disk

IDENTITY_FIELDS: Final = (
    "game_name",
    "game_version",
    "disk_number",
    "manufacturing_date",
    "writer_serial",
    "rewritten_date",
    "rewrite_count",
)

SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS dumps (
    disk_id TEXT NOT NULL,
    taken TEXT NOT NULL,
    digest TEXT NOT NULL,
    grade TEXT NOT NULL,
    confidence REAL NOT NULL,
    blocks_total INTEGER NOT NULL,
    blocks_bad INTEGER NOT NULL,
    drive TEXT NOT NULL,
    notes TEXT NOT NULL,
    PRIMARY KEY (disk_id, taken, digest)
);
CREATE INDEX IF NOT EXISTS dumps_by_disk ON dumps (disk_id, taken);
"""


@dataclass(frozen=True, slots=True)
class DumpRecord:
    disk_id: str
    taken: str
    digest: str
    grade: str
    confidence: float
    blocks_total: int
    blocks_bad: int
    drive: str = ""
    notes: str = ""

    @property
    def bad_share(self) -> float:
        if not self.blocks_total:
            return 0.0
        return self.blocks_bad / self.blocks_total


def disk_identity(disk: Disk) -> str:
    digest = hashlib.sha256()
    digest.update(str(disk.side_count).encode())
    for side in disk.sides:
        info = side.disk_info
        if info is None:
            digest.update(b"\xff")
            continue
        for name in IDENTITY_FIELDS:
            digest.update(info.raw(name))
    return digest.hexdigest()[:32]


class Archive:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection: sqlite3.Connection | None = sqlite3.connect(path)
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _live(self) -> sqlite3.Connection:
        if self._connection is None:
            message = "the archive is closed"
            raise ValueError(message)
        return self._connection

    def record(self, entry: DumpRecord) -> None:
        connection = self._live()
        connection.execute(
            "INSERT OR REPLACE INTO dumps VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.disk_id,
                entry.taken,
                entry.digest,
                entry.grade,
                entry.confidence,
                entry.blocks_total,
                entry.blocks_bad,
                entry.drive,
                entry.notes,
            ),
        )
        connection.commit()

    def history(self, disk_id: str) -> tuple[DumpRecord, ...]:
        rows = self._live().execute(
            "SELECT disk_id, taken, digest, grade, confidence, blocks_total, "
            "blocks_bad, drive, notes FROM dumps WHERE disk_id = ? ORDER BY taken",
            (disk_id,),
        )
        return tuple(DumpRecord(*row) for row in rows)

    def disks(self) -> tuple[str, ...]:
        rows = self._live().execute("SELECT DISTINCT disk_id FROM dumps ORDER BY disk_id")
        return tuple(str(row[0]) for row in rows)

    def dump_count(self) -> int:
        row = self._live().execute("SELECT COUNT(*) FROM dumps").fetchone()
        return int(row[0])

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
