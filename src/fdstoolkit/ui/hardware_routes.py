from __future__ import annotations

import base64
from collections.abc import Callable
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

from fdstoolkit.hardware.fdsstick import FdsStick, open_fdsstick
from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.hardware.session import DumpResult, dump, dump_repeated, write_verified
from fdstoolkit.quality.surface import Finish, SurfacePlan, surface_test
from fdstoolkit.ui.jobs import Controls, Job, JobBoard, JobBusyError, NotWaitingError
from fdstoolkit.ui.schemas import (
    AnswerSpec,
    CurrentJob,
    DumpedResult,
    DumpSpec,
    JobView,
    ReportedFile,
    SurfaceSpec,
    WriteSpec,
)
from fdstoolkit.ui.shared import (
    BAD_REQUEST,
    CONFLICT,
    NOT_FOUND,
    UNPROCESSABLE,
    decode_payload,
    encoded,
    named_file,
    refuse,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

BACKUP_NAME = "before.fds"


def _drive() -> FdsStick:
    try:
        return open_fdsstick()
    except HardwareFaultError as error:
        raise HTTPException(status_code=CONFLICT, detail=str(error)) from error


def _confirmed(what: str, *, confirm: bool) -> None:
    if not confirm:
        message = f"{what} destroys what is on the disk, so it needs an explicit confirm field"
        refuse(message, status=UNPROCESSABLE)


def _board(request: Request) -> JobBoard:
    board: JobBoard = request.app.state.jobs
    return board


def _view(job: Job) -> JobView:
    return JobView(
        id=job.id,
        command=job.command,
        writes=job.writes,
        state=str(job.state),
        steps=list(job.steps),
        prompt=job.prompt,
        result=job.result,
        error=job.error,
    )


def _start(
    request: Request,
    command: str,
    *,
    writes: bool,
    work: Callable[[FdsStick, Controls], BaseModel],
) -> JobView:
    board = _board(request)
    running = board.current()
    if running is not None:
        message = f"{running.command} is already running, so the drive is busy"
        raise HTTPException(status_code=CONFLICT, detail=message)
    drive = _drive()

    def run(controls: Controls) -> BaseModel:
        try:
            return work(drive, controls)
        finally:
            drive.close()

    try:
        return _view(board.start(command, writes=writes, work=run))
    except JobBusyError as error:
        drive.close()
        raise HTTPException(status_code=CONFLICT, detail=str(error)) from error


class Backup:
    def __init__(self) -> None:
        self.data = b""

    def keep(self, data: bytes) -> None:
        self.data = data


def dump_job(spec: DumpSpec, request: Request) -> JobView:
    def work(drive: FdsStick, controls: Controls) -> DumpedResult:
        if spec.passes > 1:
            result: DumpResult = dump_repeated(
                drive,
                sides=spec.sides,
                passes=spec.passes,
                retries=spec.retries,
                flip=controls.ask,
                progress=controls.step,
            ).passes[0]
        else:
            result = dump(
                drive,
                sides=spec.sides,
                retries=spec.retries,
                flip=controls.ask,
                progress=controls.step,
            )
        body = encoded(result.as_disk())
        return DumpedResult(
            name="dump.fds",
            data=base64.b64encode(body).decode("ascii"),
            size=len(body),
            grade=str(result.grade),
        )

    return _start(request, "dump", writes=False, work=work)


def write_job(spec: WriteSpec, request: Request) -> JobView:
    _confirmed("writing a disk", confirm=spec.confirm)
    disk, _, _ = decode_payload(spec.data)

    def work(drive: FdsStick, controls: Controls) -> ReportedFile:
        backup = Backup()
        report = write_verified(
            drive,
            drive,
            disk,
            confirm=lambda _: True,
            backup=backup.keep,
            retries=spec.retries,
            flip=controls.ask,
            progress=controls.step,
        )
        headline = (
            "the disk reads back as written, on this drive"
            if report.verified
            else f"{len(report.mismatched_blocks)} block(s) did not read back as written"
        )
        return ReportedFile(
            headline=headline,
            file=named_file(BACKUP_NAME, backup.data),
            rows=[{"side": side, "block": block} for side, block in report.mismatched_blocks],
            ok=report.verified,
        )

    return _start(request, "write", writes=True, work=work)


def surface_job(spec: SurfaceSpec, request: Request) -> JobView:
    _confirmed("a surface test", confirm=spec.confirm)
    try:
        finish = Finish(spec.finish)
    except ValueError as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error

    def work(drive: FdsStick, controls: Controls) -> ReportedFile:
        backup = Backup()
        report = surface_test(
            drive,
            drive,
            sides=spec.sides,
            confirm=lambda _: True,
            backup=backup.keep,
            plan=SurfacePlan(rounds=spec.passes, fill=not spec.quick, finish=finish),
            flip=controls.ask,
            progress=controls.step,
        )
        headline = (
            f"stopped early: {report.stopped.value}"
            if report.stopped is not None
            else f"grade {report.grade}"
        )
        return ReportedFile(
            headline=headline,
            file=named_file(BACKUP_NAME, backup.data),
            rows=[
                {
                    "grade": str(report.grade),
                    "coverage": report.coverage,
                    "data_bytes": report.data_bytes,
                    "hard_blocks": len(report.hard_blocks),
                    "transient_blocks": len(report.transient_blocks),
                    "recovered_blocks": len(report.recovered_blocks),
                    "finish": str(report.finish),
                    "finish_ran": report.finish_ran,
                    "finish_verified": report.finish_verified,
                    "refusal": report.refusal,
                }
            ],
            ok=report.passed,
        )

    return _start(request, "surface", writes=True, work=work)


def current_job(request: Request) -> CurrentJob:
    job = _board(request).current()
    return CurrentJob(job=None if job is None else _view(job))


def job_status(job_id: str, request: Request) -> JobView:
    job = _board(request).get(job_id)
    if job is None:
        raise HTTPException(status_code=NOT_FOUND, detail=f"there is no job {job_id}")
    return _view(job)


def job_answer(job_id: str, spec: AnswerSpec, request: Request) -> JobView:
    board = _board(request)
    try:
        board.answer(job_id, yes=spec.yes)
    except NotWaitingError as error:
        raise HTTPException(status_code=CONFLICT, detail=str(error)) from error
    return job_status(job_id, request)
