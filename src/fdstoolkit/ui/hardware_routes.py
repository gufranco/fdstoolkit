from __future__ import annotations

import base64
from collections.abc import Callable
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

from fdstoolkit.build.calibration import (
    TRUSTED_DRIVE,
    CalibrationChoiceError,
    calibration_disk,
    check_write_choice,
)
from fdstoolkit.drive.captures import bundle_zip, created_now
from fdstoolkit.drive.monitor import MAX_READS, NOT_THIS_DRIVE, Mode, RawReader, Replay, calibrate
from fdstoolkit.drive.recovery import recover
from fdstoolkit.drive.timing import (
    PROBE_WARNING,
    REPLAY_HAS_NO_TIMING,
    TIMING_OFF,
    TimingReader,
    probe,
)
from fdstoolkit.hardware.fdsstick import FdsStick, open_fdsstick
from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.hardware.session import (
    LongSideError,
    read_disk,
    refuse_long_sides,
    write_verified,
)
from fdstoolkit.quality.surface import Finish, SurfacePlan, surface_test
from fdstoolkit.ui.jobs import (
    Controls,
    Job,
    JobBoard,
    JobBusyError,
    NotStoppableError,
    NotWaitingError,
)
from fdstoolkit.ui.schemas import (
    AnswerSpec,
    CalibrateSpec,
    CalibrationResult,
    CurrentJob,
    DumpedResult,
    DumpSpec,
    JobView,
    ProbeSpec,
    ReportedFile,
    RowsResult,
    SurfaceSpec,
    WriteSpec,
)
from fdstoolkit.ui.shared import (
    BAD_REQUEST,
    CONFLICT,
    NOT_FOUND,
    UNPROCESSABLE,
    bundle_of,
    decode_payload,
    encoded,
    named_file,
    refuse,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

    from fdstoolkit.core.disk import Disk, Side

BACKUP_NAME = "before.fds"
DUMP_NAME = "dump.fds"
CAPTURES_NAME = "dump.captures.zip"


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
        stoppable=job.stoppable,
        stopping=job.stopping,
        state=str(job.state),
        steps=list(job.steps),
        prompt=job.prompt,
        result=job.result,
        error=job.error,
        kept=job.kept,
    )


def _start(
    request: Request,
    command: str,
    *,
    writes: bool,
    work: Callable[[FdsStick, Controls], BaseModel],
    stoppable: bool = False,
) -> JobView:
    _idle(request)
    drive = _drive()

    def run(controls: Controls) -> BaseModel:
        try:
            return work(drive, controls)
        finally:
            drive.close()

    try:
        return _launch(request, command, writes=writes, run=run, stoppable=stoppable)
    except HTTPException:
        drive.close()
        raise


def _idle(request: Request) -> None:
    running = _board(request).current()
    if running is not None:
        message = f"{running.command} is already running, so the drive is busy"
        raise HTTPException(status_code=CONFLICT, detail=message)


def _launch(
    request: Request,
    command: str,
    *,
    writes: bool,
    run: Callable[[Controls], BaseModel],
    stoppable: bool,
) -> JobView:
    try:
        return _view(_board(request).start(command, writes=writes, work=run, stoppable=stoppable))
    except JobBusyError as error:
        raise HTTPException(status_code=CONFLICT, detail=str(error)) from error


class Backup:
    def __init__(self, controls: Controls) -> None:
        self.data = b""
        self._controls = controls

    def keep(self, data: bytes) -> None:
        self.data = data
        self._controls.keep(named_file(BACKUP_NAME, data).model_dump())


def dump_job(spec: DumpSpec, request: Request) -> JobView:
    def work(drive: FdsStick, controls: Controls) -> DumpedResult:
        reading = read_disk(
            drive,
            sides=spec.sides,
            passes=spec.passes,
            retries=spec.retries,
            flip=controls.ask,
            progress=controls.step,
        )
        outcome = recover(reading.result, drive.captures)
        report = [
            *reading.lines,
            *(line.strip() for line in outcome.lines),
            *(line for side in outcome.result.sides for line in side.lines),
        ]
        for line in report:
            controls.step(line)
        body = encoded(outcome.result.as_disk())
        kept = (
            named_file(
                CAPTURES_NAME,
                bundle_zip(drive.captures, image=DUMP_NAME, created=created_now()),
            )
            if spec.keep_captures and drive.captures
            else None
        )
        return DumpedResult(
            name=DUMP_NAME,
            data=base64.b64encode(body).decode("ascii"),
            size=len(body),
            grade=str(reading.settled(outcome.result, changed=bool(outcome.recovered))),
            captures=kept,
        )

    return _start(request, "dump", writes=False, work=work)


def _write_target(spec: WriteSpec) -> Disk:
    try:
        check_write_choice(
            has_image=spec.data is not None,
            calibration=spec.calibration,
            trusted_drive=spec.trusted_drive,
        )
    except CalibrationChoiceError as error:
        detail = str(error)
        if spec.calibration:
            detail = "\n".join([detail, *TRUSTED_DRIVE])
        raise HTTPException(status_code=UNPROCESSABLE, detail=detail) from error
    disk = calibration_disk() if spec.data is None else decode_payload(spec.data)[0]
    if not spec.long_side:
        try:
            refuse_long_sides(disk)
        except LongSideError as error:
            detail = f"{error}. Tick long side to write it anyway"
            raise HTTPException(status_code=UNPROCESSABLE, detail=detail) from error
    return disk


def write_job(spec: WriteSpec, request: Request) -> JobView:
    _confirmed("writing a disk", confirm=spec.confirm)
    disk = _write_target(spec)

    def work(drive: FdsStick, controls: Controls) -> ReportedFile:
        if spec.calibration:
            for line in TRUSTED_DRIVE:
                controls.step(line)
        backup = Backup(controls)
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
        for note in report.notes:
            controls.step(note)
        headline = (
            "the disk reads back as written, on this drive"
            if report.verified
            else f"{len(report.mismatched_blocks)} block(s) did not read back as written"
        )
        return ReportedFile(
            headline=headline,
            file=named_file(BACKUP_NAME, backup.data),
            rows=[
                {"side": side, "block": block, "finding": text}
                for side, block, text in report.findings
            ],
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
        backup = Backup(controls)
        report = surface_test(
            drive,
            drive,
            sides=spec.sides,
            confirm=lambda _: True,
            backup=backup.keep,
            plan=SurfacePlan(
                rounds=spec.passes,
                fill=not spec.quick,
                finish=finish,
                stopped=controls.stopped,
            ),
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
                    "finish_problem": report.finish_problem or None,
                    "refusal": report.refusal,
                    "pulses": report.pulse_summary or None,
                    "where": report.wear_hint or None,
                    "advice": report.advice or None,
                }
            ],
            ok=report.passed,
        )

    return _start(request, "surface", writes=True, work=work, stoppable=True)


def calibrate_job(spec: CalibrateSpec, request: Request) -> JobView:
    try:
        mode = Mode(spec.mode)
    except ValueError as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    wanted = None
    if spec.reference is not None:
        disk, _, _ = decode_payload(spec.reference)
        if spec.side >= disk.side_count:
            message = f"the reference has {disk.side_count} side(s), so it has no side {spec.side}"
            raise HTTPException(status_code=UNPROCESSABLE, detail=message)
        wanted = disk.sides[spec.side]

    if spec.captures is not None:
        replay = _replay(spec.captures, spec.side)

        def offline(controls: Controls) -> CalibrationResult:
            if spec.timing_mode is not None:
                controls.step(REPLAY_HAS_NO_TIMING)
            return _calibrated(
                replay, controls, mode=mode, reads=len(replay.captures), wanted=wanted
            )

        _idle(request)
        return _launch(request, "calibrate", writes=False, run=offline, stoppable=True)

    def work(drive: FdsStick, controls: Controls) -> CalibrationResult:
        controls.step(NOT_THIS_DRIVE)
        reader: RawReader = drive
        if spec.timing_mode is None:
            controls.step(TIMING_OFF)
        else:
            reader = TimingReader(drive, mode=spec.timing_mode, note=controls.step)
        return _calibrated(
            reader,
            controls,
            mode=mode,
            reads=spec.passes,
            wanted=wanted,
            bracket=spec.bracket,
        )

    return _start(request, "calibrate", writes=False, work=work, stoppable=True)


def probe_job(spec: ProbeSpec, request: Request) -> JobView:
    if not spec.confirm:
        refuse(PROBE_WARNING, status=UNPROCESSABLE)

    def work(drive: FdsStick, controls: Controls) -> RowsResult:
        found = probe(drive, progress=controls.step)
        prefix = "" if found.timing_mode is not None else "warning: "
        return RowsResult(
            headline=f"{prefix}{found.verdict}",
            rows=[
                {
                    "mode": f"{result.mode:#04x}",
                    "answer": result.nature.value,
                    "detail": result.detail,
                }
                for result in found.results
            ],
            ok=found.timing_mode is not None,
        )

    return _start(request, "probe", writes=True, work=work)


def _replay(payload: str, side: int) -> Replay:
    saved = bundle_of(payload).of_side(side)[:MAX_READS]
    if not saved:
        message = f"the captures hold no read of side {side}"
        raise HTTPException(status_code=UNPROCESSABLE, detail=message)
    return Replay(saved)


def _calibrated(
    reader: RawReader,
    controls: Controls,
    *,
    mode: Mode,
    reads: int,
    wanted: Side | None,
    bracket: bool = False,
) -> CalibrationResult:
    result = calibrate(
        reader,
        mode=mode,
        reads=reads,
        reference=wanted,
        progress=controls.step,
        stopped=controls.stopped,
        bracket=controls.ask if bracket else None,
    )
    return CalibrationResult.of(result)


def current_job(request: Request) -> CurrentJob:
    job = _board(request).current()
    return CurrentJob(job=None if job is None else _view(job))


def job_status(job_id: str, request: Request) -> JobView:
    job = _board(request).get(job_id)
    if job is None:
        raise HTTPException(status_code=NOT_FOUND, detail=f"there is no job {job_id}")
    return _view(job)


def job_stop(job_id: str, request: Request) -> JobView:
    try:
        _board(request).stop(job_id)
    except NotStoppableError as error:
        raise HTTPException(status_code=CONFLICT, detail=str(error)) from error
    return job_status(job_id, request)


def job_answer(job_id: str, spec: AnswerSpec, request: Request) -> JobView:
    board = _board(request)
    try:
        board.answer(job_id, yes=spec.yes)
    except NotWaitingError as error:
        raise HTTPException(status_code=CONFLICT, detail=str(error)) from error
    return job_status(job_id, request)
