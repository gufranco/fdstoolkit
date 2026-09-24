from __future__ import annotations

import base64

from fastapi import HTTPException

from fdstoolkit.hardware.fdsstick import FdsStick, open_fdsstick
from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.hardware.session import (
    SideFlipError,
    WriteRefusedError,
    dump,
    write_verified,
)
from fdstoolkit.quality.surface import (
    Finish,
    SurfacePlan,
    SurfaceTestRefusedError,
    surface_test,
)
from fdstoolkit.ui.schemas import (
    DumpedResult,
    DumpSpec,
    RowsResult,
    SurfaceSpec,
    WriteSpec,
)
from fdstoolkit.ui.shared import (
    BAD_REQUEST,
    CONFLICT,
    UNPROCESSABLE,
    decode_payload,
    encoded,
    refuse,
)


def _drive() -> FdsStick:
    try:
        return open_fdsstick()
    except HardwareFaultError as error:
        raise HTTPException(status_code=CONFLICT, detail=str(error)) from error


def _confirmed(what: str, *, confirm: bool) -> None:
    if not confirm:
        message = f"{what} destroys what is on the disk, so it needs an explicit confirm field"
        refuse(message, status=UNPROCESSABLE)


def dump_route(spec: DumpSpec) -> DumpedResult:
    drive = _drive()
    try:
        result = dump(drive, sides=spec.sides, retries=spec.retries)
    except (HardwareFaultError, WriteRefusedError, SideFlipError) as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    body = encoded(result.as_disk())
    return DumpedResult(
        name="dump.fds",
        data=base64.b64encode(body).decode("ascii"),
        size=len(body),
        grade=str(result.grade),
    )


def write_route(spec: WriteSpec) -> RowsResult:
    _confirmed("writing a disk", confirm=spec.confirm)
    disk, _, _ = decode_payload(spec.data)
    drive = _drive()
    try:
        report = write_verified(
            drive,
            drive,
            disk,
            confirm=lambda _: True,
            backup=None,
            retries=spec.retries,
            skip_backup=True,
        )
    except (HardwareFaultError, WriteRefusedError) as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    return RowsResult(
        rows=[
            {
                "verified": report.verified,
                "grade": str(report.grade),
                "mismatched": len(report.mismatched_blocks),
            }
        ],
        ok=report.verified,
    )


def surface_route(spec: SurfaceSpec) -> RowsResult:
    _confirmed("a surface test", confirm=spec.confirm)
    drive = _drive()
    try:
        finish = Finish(spec.finish)
    except ValueError as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    try:
        report = surface_test(
            drive,
            drive,
            sides=spec.sides,
            confirm=lambda _: True,
            plan=SurfacePlan(rounds=spec.passes, fill=not spec.quick, finish=finish),
        )
    except (HardwareFaultError, WriteRefusedError, SurfaceTestRefusedError) as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    return RowsResult(
        rows=[
            {
                "grade": str(report.grade),
                "coverage": report.coverage,
                "data_bytes": report.data_bytes,
                "hard_blocks": len(report.hard_blocks),
                "transient_blocks": len(report.transient_blocks),
                "recovered_blocks": len(report.recovered_blocks),
                "finish": str(report.finish),
                "finish_verified": report.finish_verified,
            }
        ],
        ok=report.finish_verified,
    )
