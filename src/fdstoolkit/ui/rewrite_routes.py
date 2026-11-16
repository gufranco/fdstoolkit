from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Final

from fastapi import Request  # noqa: TC002

from fdstoolkit.quality.surface_disks import erased_disk
from fdstoolkit.ui.hardware_routes import confirmed, start_drive_job, write_reported
from fdstoolkit.ui.rewrite_schemas import EraseSpec
from fdstoolkit.ui.schemas import JobView, ReportedFile

if TYPE_CHECKING:
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
