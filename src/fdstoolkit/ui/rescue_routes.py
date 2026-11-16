from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Final

from fastapi import HTTPException, Request

from fdstoolkit.drive.rescue import (
    EMPTY,
    IMAGE_NAME,
    RescueError,
    RescueState,
    load_zip,
    progress_of,
    read_into,
    side_settled,
    state_zip,
)
from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.ui.hardware_routes import start_drive_job
from fdstoolkit.ui.schemas import FileResult, JobView, RescueResult, RescueSpec
from fdstoolkit.ui.shared import BAD_REQUEST, bytes_of, encoded_file, named_file

if TYPE_CHECKING:
    from fdstoolkit.hardware.fdsstick import FdsStick
    from fdstoolkit.ui.jobs import Controls

RESCUE_ZIP: Final = "rescue.zip"


def _zipped(state: RescueState) -> FileResult:
    return named_file(RESCUE_ZIP, state_zip(state))


def _gathered(
    spec: RescueSpec, state: RescueState, drive: FdsStick, controls: Controls
) -> RescueState:
    current = state
    try:
        for _ in range(spec.passes):
            if controls.stopped():
                break
            controls.step(
                f"reading side {spec.side}, read {current.reads_of(spec.side) + 1} of the rescue"
            )
            current = read_into(current, drive, spec.side)
            if side_settled(current, spec.side):
                break
    except (RescueError, HardwareFaultError):
        controls.keep(_zipped(current).model_dump())
        raise
    return current


def _rescue(
    spec: RescueSpec, state: RescueState, drive: FdsStick, controls: Controls
) -> RescueResult:
    current = _gathered(spec, state, drive, controls)
    progress = progress_of(current)
    for line in progress.lines:
        controls.step(line.strip())
    image = encoded_file(IMAGE_NAME, progress.disk) if progress.settled else None
    return RescueResult(**_zipped(current).model_dump(), settled=progress.settled, image=image)


def _kept(payload: str | None) -> RescueState:
    if payload is None:
        return EMPTY
    try:
        return load_zip(bytes_of(payload))
    except RescueError as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error


def rescue_job(spec: RescueSpec, request: Request) -> JobView:
    state = _kept(spec.captures)
    work = partial(_rescue, spec, state)
    return start_drive_job(request, "rescue", writes=False, work=work, stoppable=True)
