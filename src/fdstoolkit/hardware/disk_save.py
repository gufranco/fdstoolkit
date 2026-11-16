from __future__ import annotations

from collections.abc import Callable
from typing import Final, Protocol

from fdstoolkit.codecs import fds
from fdstoolkit.core.disk import SIDE_SIZE, Disk, Side
from fdstoolkit.edit.disk_saves import SaveBackup, backup_of, restored
from fdstoolkit.hardware.ports import DiskReader, DiskWriter
from fdstoolkit.hardware.session import (
    Progress,
    SideDump,
    WriteRefusedError,
    quiet,
    read_side_with_retries,
)
from fdstoolkit.hardware.writing import SideWrite, write_side_verified

DECLINED: Final = "the operator declined the write"


class SaveDrive(DiskReader, DiskWriter, Protocol):
    pass


def read_clean_side(
    reader: DiskReader, side: int, retries: int, progress: Progress = quiet
) -> Side:
    progress(f"reading side {side}")
    dumped = SideDump(index=side, blocks=read_side_with_retries(reader, side, retries))
    if dumped.failed_blocks or dumped.missing_blocks or not dumped.blocks:
        failed = ", ".join(str(block) for block in dumped.failed_blocks) or "none"
        message = (
            f"side {side} did not read clean, blocks {failed} never read, so it cannot carry a "
            "save; clean the disk and try again, or rescue it first"
        )
        raise WriteRefusedError(message)
    return dumped.as_side(SIDE_SIZE)


def back_up_save(
    reader: DiskReader, *, side: int, number: int | None, retries: int, progress: Progress = quiet
) -> SaveBackup:
    return backup_of(side, read_clean_side(reader, side, retries, progress), number)


def _require_writable(writer: DiskWriter) -> None:
    status = writer.status()
    if not status.can_write:
        message = f"cannot write: {', '.join(status.blockers)}"
        raise WriteRefusedError(message)


def restore_save(
    drive: SaveDrive,
    backup: SaveBackup,
    *,
    retries: int,
    confirm: Callable[[str], bool],
    keep: Callable[[bytes], None],
    progress: Progress = quiet,
) -> SideWrite:
    _require_writable(drive)
    present = read_clean_side(drive, backup.side, retries, progress)
    target = restored(backup.side, present, backup)
    if not confirm(f"rewrite side {backup.side} with file {backup.number} {backup.name} restored"):
        raise WriteRefusedError(DECLINED)

    def kept(before: SideDump) -> None:
        data, _ = fds.encode(Disk(sides=(before.as_side(SIDE_SIZE),)), headered=False)
        keep(data)

    return write_side_verified(
        drive, drive, backup.side, target, retries=retries, progress=progress, before_write=kept
    )
