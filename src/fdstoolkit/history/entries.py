from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from fdstoolkit.core.disk import Disk
from fdstoolkit.doctor import Enumerator, load_hid
from fdstoolkit.drive.captures import Bundle, Capture, created_now
from fdstoolkit.drive.monitor import Calibration
from fdstoolkit.drive.weak import bundle_weak_blocks
from fdstoolkit.hardware.fdsstick import PRODUCT_ID, VENDOR_ID
from fdstoolkit.hardware.session import DumpResult, Grade
from fdstoolkit.history.logbook import Entry, EntryKind

DRIVE_ENV: Final = "FDSTOOLKIT_DRIVE"
DEFAULT_DRIVE: Final = "drive"
DIGEST_CHARS: Final = 16
UNNAMED: Final = "unnamed disk"
UNIDENTIFIED: Final = "unidentified disk"
IN_THE_DRIVE: Final = "the disk in the drive"
CLEAN: Final = "clean"
NOT_CLEAN: Final = "not clean"

Pair = tuple[int, int]


@dataclass(frozen=True, slots=True)
class Stamp:
    run: str
    recorded: str


@dataclass(frozen=True, slots=True)
class DiskKey:
    id: str
    title: str


@dataclass(frozen=True, slots=True)
class DriveKey:
    stick: str | None
    drive: str


def stamp_now() -> Stamp:
    return Stamp(run=uuid.uuid4().hex, recorded=created_now())


def disk_key(disk: Disk) -> DiskKey | None:
    info = disk.sides[0].disk_info if disk.sides else None
    if info is None:
        return None
    digest = hashlib.sha256(info.payload).hexdigest()[:DIGEST_CHARS]
    return DiskKey(id=f"disk-{digest}", title=info.game_name.strip() or UNNAMED)


def _stick_serial(loader: Callable[[], Enumerator]) -> str | None:
    try:
        found = loader().enumerate(VENDOR_ID, PRODUCT_ID)
    except (ImportError, OSError):
        return None
    serials = [str(entry.get("serial_number") or "").strip() for entry in found]
    return next((serial for serial in serials if serial), None)


def drive_key(loader: Callable[[], Enumerator] = load_hid) -> DriveKey:
    label = os.environ.get(DRIVE_ENV, "").strip() or DEFAULT_DRIVE
    return DriveKey(stick=_stick_serial(loader), drive=label)


def _weak_in(captures: Sequence[Capture]) -> set[Pair]:
    bundle = Bundle(captures=tuple(captures), image="", created="")
    return {(side, entry.block) for side, entry in bundle_weak_blocks(bundle)}


def _entry(
    stamp: Stamp,
    kind: EntryKind,
    disk: Disk | None,
    *,
    grade: str,
    weak: set[Pair],
    drive: DriveKey | None,
) -> Entry:
    key = None if disk is None else disk_key(disk)
    fallback = IN_THE_DRIVE if disk is None else UNIDENTIFIED
    return Entry(
        run=stamp.run,
        recorded=stamp.recorded,
        kind=kind,
        disk=None if key is None else key.id,
        title=fallback if key is None else key.title,
        stick=None if drive is None else drive.stick,
        drive=None if drive is None else drive.drive,
        grade=grade,
        weak=tuple(sorted(weak)),
    )


def dump_entry(
    stamp: Stamp,
    result: DumpResult,
    captures: Sequence[Capture],
    *,
    grade: Grade,
    drive: DriveKey,
) -> Entry:
    read = {
        (side.index, index)
        for side in result.sides
        for index in (*side.marginal_blocks, *side.failed_blocks)
    }
    weak = read | _weak_in(captures)
    return _entry(
        stamp, EntryKind.DUMP, result.as_disk(), grade=grade.value, weak=weak, drive=drive
    )


def grade_entry(stamp: Stamp, disk: Disk, grade: Grade, captures: Sequence[Capture]) -> Entry:
    failing = {
        (number, index)
        for number, side in enumerate(disk.sides)
        for index, block in enumerate(side.blocks)
        if block.stored_crc is not None and block.stored_crc != block.computed_crc
    }
    weak = failing | _weak_in(captures)
    return _entry(stamp, EntryKind.GRADE, disk, grade=grade.value, weak=weak, drive=None)


def calibration_entry(
    stamp: Stamp,
    result: Calibration,
    *,
    side: int,
    reference: Disk | None,
    drive: DriveKey,
) -> Entry:
    weak = {(side, index) for sample in result.samples for index in sample.missing}
    grade = CLEAN if result.clean else NOT_CLEAN
    return _entry(stamp, EntryKind.CALIBRATION, reference, grade=grade, weak=weak, drive=drive)
