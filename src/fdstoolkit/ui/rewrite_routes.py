from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Final

from fastapi import Request  # noqa: TC002

from fdstoolkit.hardware.duplicate import duplicate, duplicate_lines
from fdstoolkit.hardware.session import LongSideError
from fdstoolkit.hardware.writing import refuse_long_sides
from fdstoolkit.quality.surface_disks import erased_disk
from fdstoolkit.ui.hardware_routes import confirmed, start_drive_job, write_reported
from fdstoolkit.ui.history_schemas import CopyView, DuplicateResult
from fdstoolkit.ui.rewrite_schemas import DuplicateSpec, EraseSpec
from fdstoolkit.ui.schemas import JobView, ReportedFile
from fdstoolkit.ui.shared import UNPROCESSABLE, decode_payload, refuse

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
