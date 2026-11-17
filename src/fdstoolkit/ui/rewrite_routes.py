from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Final

from fastapi import Request  # noqa: TC002

from fdstoolkit.edit.disk_saves import SaveBackup, SaveBackupError, backup_bytes, load_backup
from fdstoolkit.hardware.disk_save import back_up_save, restore_save
from fdstoolkit.hardware.duplicate import duplicate, duplicate_lines
from fdstoolkit.hardware.refresh import RefreshPlan, refresh_disk
from fdstoolkit.hardware.session import LongSideError
from fdstoolkit.hardware.writing import CHANGED_BLOCK, STALE_BLOCK, refuse_long_sides
from fdstoolkit.quality.checker import CHECKER_ALONE, SurfaceKind, run_checker
from fdstoolkit.quality.surface import Finish
from fdstoolkit.quality.surface_disks import erased_disk
from fdstoolkit.ui import hardware_routes
from fdstoolkit.ui.hardware_routes import (
    BACKUP_NAME,
    Backup,
    confirmed,
    start_drive_job,
    write_reported,
)
from fdstoolkit.ui.history_schemas import CopyView, DuplicateResult
from fdstoolkit.ui.rewrite_schemas import (
    DuplicateSpec,
    EraseSpec,
    RefreshSpec,
    SaveBackupSpec,
    SaveRestoreSpec,
)
from fdstoolkit.ui.schemas import JobView, ReportedFile, SurfaceSpec
from fdstoolkit.ui.shared import (
    UNPROCESSABLE,
    bytes_of,
    decode_payload,
    encoded_file,
    named_file,
    refuse,
)

if TYPE_CHECKING:
    from fdstoolkit.core.disk import Disk
    from fdstoolkit.hardware.fdsstick import FdsStick
    from fdstoolkit.ui.jobs import Controls

ERASED: Final = "every side reads back with no block"


def _erase(spec: EraseSpec, drive: FdsStick, controls: Controls) -> ReportedFile:
    reported = write_reported(erased_disk(sides=spec.sides), spec.retries, drive, controls)
    if not reported.ok:
        return reported
    return reported.model_copy(update={"headline": ERASED})


def erase_job(spec: EraseSpec, request: Request) -> JobView:
    confirmed("erasing a disk", confirm=spec.confirm)
    return start_drive_job(request, "erase", writes=True, work=partial(_erase, spec))


def _duplicate(
    spec: DuplicateSpec, disk: Disk, drive: FdsStick, controls: Controls
) -> DuplicateResult:
    report = duplicate(
        drive,
        drive,
        disk,
        count=spec.count,
        ask=controls.ask,
        retries=spec.retries,
        progress=controls.step,
    )
    lines = duplicate_lines(report)
    for line in lines[:-1]:
        controls.step(line)
    copies = [
        CopyView(number=copy.number, verified=copy.verified, grade=copy.grade, reason=copy.reason)
        for copy in report.copies
    ]
    return DuplicateResult(headline=lines[-1], ok=report.verified == spec.count, copies=copies)


def duplicate_job(spec: DuplicateSpec, request: Request) -> JobView:
    confirmed("duplicating onto disks", confirm=spec.confirm)
    disk = decode_payload(spec.data)[0]
    try:
        refuse_long_sides(disk)
    except LongSideError as error:
        refuse(str(error), status=UNPROCESSABLE)
    work = partial(_duplicate, spec, disk)
    return start_drive_job(request, "duplicate", writes=True, work=work)


REFRESHED_NAME: Final = "refreshed.fds"


def _refresh(spec: RefreshSpec, drive: FdsStick, controls: Controls) -> ReportedFile:
    backup = Backup(controls)
    kept: list[Disk] = []
    plan = RefreshPlan(
        sides=spec.sides,
        passes=spec.passes,
        retries=spec.retries,
        ask=controls.ask,
        keep=kept.append,
        backup=backup.keep,
        progress=controls.step,
    )
    report = refresh_disk(drive, plan)
    for line in (*report.lines, *report.write.notes):
        controls.step(line)
    rows: list[dict[str, object]] = [
        {"side": side, "block": block, "finding": text}
        for side, block, text in report.write.findings
    ]
    headline = (
        f"the disk reads back as rebuilt, on this drive, grade {report.write.grade}"
        if report.write.verified
        else f"{len(report.write.mismatched_blocks)} block(s) did not read back as written"
    )
    image = encoded_file(REFRESHED_NAME, kept[0])
    return ReportedFile(headline=headline, file=image, rows=rows, ok=report.write.verified)


def refresh_job(spec: RefreshSpec, request: Request) -> JobView:
    confirmed("refreshing a disk", confirm=spec.confirm)
    return start_drive_job(request, "refresh", writes=True, work=partial(_refresh, spec))


SAVE_NAME: Final = "save.json"


def _save_backup(spec: SaveBackupSpec, drive: FdsStick, controls: Controls) -> ReportedFile:
    backup = back_up_save(
        drive, side=spec.side, number=spec.file, retries=spec.retries, progress=controls.step
    )
    headline = (
        f"kept file {backup.number} {backup.name}, {len(backup.data)} bytes, of "
        f"{backup.identity.render()} side {backup.side}"
    )
    return ReportedFile(headline=headline, file=named_file(SAVE_NAME, backup_bytes(backup)))


def save_backup_job(spec: SaveBackupSpec, request: Request) -> JobView:
    work = partial(_save_backup, spec)
    return start_drive_job(request, "save-backup", writes=False, work=work)


def _save_restore(
    spec: SaveRestoreSpec, kept: SaveBackup, drive: FdsStick, controls: Controls
) -> ReportedFile:
    backup = Backup(controls)
    written = restore_save(
        drive,
        kept,
        retries=spec.retries,
        confirm=lambda _: True,
        keep=backup.keep,
        progress=controls.step,
    )
    rows: list[dict[str, object]] = [
        {
            "side": kept.side,
            "block": block,
            "finding": STALE_BLOCK if block in written.stale else CHANGED_BLOCK,
        }
        for block in written.mismatched
    ]
    state = "did not read back as written" if written.mismatched else "read back as written"
    headline = f"restored file {kept.number} {kept.name} on side {kept.side}, {state}"
    return ReportedFile(
        headline=headline, file=named_file(BACKUP_NAME, backup.data), rows=rows, ok=not rows
    )


def save_restore_job(spec: SaveRestoreSpec, request: Request) -> JobView:
    confirmed("restoring a save", confirm=spec.confirm)
    try:
        kept = load_backup(bytes_of(spec.saved))
    except SaveBackupError as error:
        refuse(str(error), status=UNPROCESSABLE)
    return start_drive_job(
        request, "save-restore", writes=True, work=partial(_save_restore, spec, kept)
    )


def _checker(spec: SurfaceSpec, drive: FdsStick, controls: Controls) -> ReportedFile:
    backup = Backup(controls)
    readings = run_checker(
        drive,
        sides=spec.sides,
        confirm=lambda _: True,
        flip=controls.ask,
        keep=backup.keep,
        progress=controls.step,
    )
    rows: list[dict[str, object]] = [
        {"side": reading.side, "matched": reading.matched, "expected": reading.expected}
        for reading in readings
    ]
    verified = all(reading.verified for reading in readings)
    headline = "; ".join(reading.render() for reading in readings)
    file = named_file(BACKUP_NAME, backup.data)
    return ReportedFile(headline=headline, file=file, rows=rows, ok=verified)


def surface_job(spec: SurfaceSpec, request: Request) -> JobView:
    if spec.pattern != SurfaceKind.CHECKER:
        return hardware_routes.surface_job(spec, request)
    confirmed("a surface test", confirm=spec.confirm)
    if spec.passes != 1 or spec.quick or spec.finish != Finish.LEAVE:
        refuse(CHECKER_ALONE, status=UNPROCESSABLE)
    return start_drive_job(request, "surface", writes=True, work=partial(_checker, spec))
