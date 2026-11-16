from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

from fdstoolkit.build.calibration import (
    TRUSTED_DRIVE,
    CalibrationChoiceError,
    calibration_disk,
    check_write_choice,
)
from fdstoolkit.drive.captures import bundle_zip, created_now
from fdstoolkit.drive.monitor import (
    MAX_READS,
    NOT_THIS_DRIVE,
    Calibration,
    Mode,
    RawReader,
    Replay,
    calibrate,
)
from fdstoolkit.drive.pulse import pulse_lines
from fdstoolkit.drive.recognition import rate_lines
from fdstoolkit.drive.recovery import recover
from fdstoolkit.drive.timing import TimingReader
from fdstoolkit.hardware.fdsstick import FdsStick, link_note, open_fdsstick
from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.hardware.session import (
    LongSideError,
    Reading,
    SideFlipError,
    WriteRefusedError,
    read_disk,
)
from fdstoolkit.hardware.writing import refuse_long_sides, write_verified
from fdstoolkit.history.checks import check_entry, drift_of, drift_payload
from fdstoolkit.history.entries import calibration_entry, drive_key, dump_entry, stamp_now
from fdstoolkit.history.logbook import Entry, LogbookError, history, logbook_path, record
from fdstoolkit.quality.surface import Finish, SurfacePlan, SurfaceReport, surface_test
from fdstoolkit.ui.history_schemas import SessionResult, SessionSpec
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
    FileResult,
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
    bundle_of,
    decode_payload,
    encoded_file,
    named_file,
    refuse,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

    from fdstoolkit.core.disk import Disk, Side

BACKUP_NAME = "before.fds"
DUMP_NAME = "dump.fds"
DUMP_STOPS = (HardwareFaultError, WriteRefusedError, SideFlipError)
DUMP_QD_NAME = "dump.qd"
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
    return JobView.model_validate(
        {
            "id": job.id,
            "command": job.command,
            "writes": job.writes,
            "stoppable": job.stoppable,
            "stopping": job.stopping,
            "state": str(job.state),
            "steps": list(job.steps),
            "prompt": job.prompt,
            "result": job.result,
            "error": job.error,
            "kept": job.kept,
        }
    )


def start_drive_job(
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
    except BaseException:
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


def _drive_lines(drive: FdsStick) -> tuple[str, ...]:
    note = link_note(drive.resyncs)
    return (
        *pulse_lines(drive.pulse_findings, drive.captures),
        *rate_lines(drive.captures),
        *((note,) if note else ()),
    )


def _keep_failed_captures(spec: DumpSpec, drive: FdsStick, controls: Controls) -> None:
    for line in _drive_lines(drive):
        controls.step(line)
    if spec.keep_captures and drive.captures:
        bundle = bundle_zip(drive.captures, image=DUMP_NAME, created=created_now())
        controls.keep(named_file(CAPTURES_NAME, bundle).model_dump())


def _read_for_dump(spec: DumpSpec, drive: FdsStick, controls: Controls) -> Reading:
    try:
        return read_disk(
            drive,
            sides=spec.sides,
            passes=spec.passes,
            retries=spec.retries,
            flip=controls.ask,
            progress=controls.step,
        )
    except DUMP_STOPS:
        _keep_failed_captures(spec, drive, controls)
        raise


def _dump(spec: DumpSpec, drive: FdsStick, controls: Controls) -> DumpedResult:
    reading = _read_for_dump(spec, drive, controls)
    outcome = recover(reading.result, drive.captures)
    report = [
        *reading.lines,
        *(line.strip() for line in outcome.lines),
        *(line for side in outcome.result.sides for line in side.lines),
    ]
    for line in (*report, *_drive_lines(drive)):
        controls.step(line)
    name = DUMP_QD_NAME if spec.qd else DUMP_NAME
    image = encoded_file(name, outcome.result.as_disk())
    kept = None
    if spec.keep_captures and drive.captures:
        bundle = bundle_zip(drive.captures, image=name, created=created_now())
        kept = named_file(CAPTURES_NAME, bundle)
    grade = reading.settled(outcome.result, changed=bool(outcome.recovered))
    entry = dump_entry(stamp_now(), outcome.result, drive.captures, grade=grade, drive=drive_key())
    _logged(entry, controls, image)
    return DumpedResult(**image.model_dump(), grade=str(grade), captures=kept)


def _logged(entry: Entry, controls: Controls, image: FileResult | None = None) -> None:
    try:
        record(entry)
    except LogbookError:
        if image is not None:
            controls.keep(image.model_dump())
        raise
    controls.step(f"logged under {entry.disk or entry.title} in {logbook_path()}")


def _session(
    spec: SessionSpec, wanted: Disk | None, drive: FdsStick, controls: Controls
) -> SessionResult:
    key = drive_key()
    earlier = history(logbook_path(), drive=key.drive)
    reading = read_disk(drive, sides=1, passes=1, retries=spec.retries, progress=controls.step)
    entry = check_entry(stamp_now(), reading.result, wanted, key)
    _logged(entry, controls)
    return SessionResult.model_validate(drift_payload(drift_of(earlier, entry)))


def session_job(spec: SessionSpec, request: Request) -> JobView:
    wanted = None if spec.reference is None else decode_payload(spec.reference)[0]
    return start_drive_job(request, "session", writes=False, work=partial(_session, spec, wanted))


def dump_job(spec: DumpSpec, request: Request) -> JobView:
    return start_drive_job(request, "dump", writes=False, work=partial(_dump, spec))


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


def _write(spec: WriteSpec, disk: Disk, drive: FdsStick, controls: Controls) -> ReportedFile:
    for line in TRUSTED_DRIVE if spec.calibration else ():
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
        f"the disk reads back as written, on this drive, grade {report.grade}"
        if report.verified
        else f"{len(report.mismatched_blocks)} block(s) did not read back as written"
    )
    rows: list[dict[str, object]] = [
        {"side": side, "block": block, "finding": text} for side, block, text in report.findings
    ]
    file = named_file(BACKUP_NAME, backup.data)
    return ReportedFile(headline=headline, file=file, rows=rows, ok=report.verified)


def write_job(spec: WriteSpec, request: Request) -> JobView:
    _confirmed("writing a disk", confirm=spec.confirm)
    disk = _write_target(spec)
    return start_drive_job(request, "write", writes=True, work=partial(_write, spec, disk))


def _surface_row(report: SurfaceReport) -> dict[str, object]:
    return {
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


def _surface(
    spec: SurfaceSpec, finish: Finish, drive: FdsStick, controls: Controls
) -> ReportedFile:
    backup = Backup(controls)
    plan = SurfacePlan(
        rounds=spec.passes, fill=not spec.quick, finish=finish, stopped=controls.stopped
    )
    report = surface_test(
        drive,
        drive,
        sides=spec.sides,
        confirm=lambda _: True,
        backup=backup.keep,
        plan=plan,
        flip=controls.ask,
        progress=controls.step,
    )
    stopped = report.stopped
    headline = f"stopped early: {stopped.value}" if stopped is not None else f"grade {report.grade}"
    file = named_file(BACKUP_NAME, backup.data)
    return ReportedFile(headline=headline, file=file, rows=[_surface_row(report)], ok=report.passed)


def surface_job(spec: SurfaceSpec, request: Request) -> JobView:
    _confirmed("a surface test", confirm=spec.confirm)
    try:
        finish = Finish(spec.finish)
    except ValueError as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    work = partial(_surface, spec, finish)
    return start_drive_job(request, "surface", writes=True, work=work, stoppable=True)


def _reference_side(spec: CalibrateSpec) -> Side | None:
    if spec.reference is None:
        return None
    disk, _, _ = decode_payload(spec.reference)
    if spec.side >= disk.side_count:
        message = f"the reference has {disk.side_count} side(s), so it has no side {spec.side}"
        raise HTTPException(status_code=UNPROCESSABLE, detail=message)
    return disk.sides[spec.side]


def _live_calibration(
    spec: CalibrateSpec, mode: Mode, wanted: Side | None, drive: FdsStick, controls: Controls
) -> CalibrationResult:
    controls.step(NOT_THIS_DRIVE)
    reader = TimingReader(drive, note=controls.step)
    result = _calibrated(
        reader, controls, mode=mode, reads=spec.passes, wanted=wanted, bracket=spec.bracket
    )
    reference = None if spec.reference is None else decode_payload(spec.reference)[0]
    entry = calibration_entry(
        stamp_now(), result, side=spec.side, reference=reference, drive=drive_key()
    )
    _logged(entry, controls)
    return CalibrationResult.of(result, reader.timings)


def _replayed(
    replay: Replay, mode: Mode, wanted: Side | None, controls: Controls
) -> CalibrationResult:
    result = _calibrated(replay, controls, mode=mode, reads=len(replay.captures), wanted=wanted)
    return CalibrationResult.of(result)


def calibrate_job(spec: CalibrateSpec, request: Request) -> JobView:
    try:
        mode = Mode(spec.mode)
    except ValueError as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    wanted = _reference_side(spec)
    if spec.captures is None:
        work = partial(_live_calibration, spec, mode, wanted)
        return start_drive_job(request, "calibrate", writes=False, work=work, stoppable=True)
    offline = partial(_replayed, _replay(spec.captures, spec.side), mode, wanted)
    _idle(request)
    return _launch(request, "calibrate", writes=False, run=offline, stoppable=True)


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
) -> Calibration:
    return calibrate(
        reader,
        mode=mode,
        reads=reads,
        reference=wanted,
        progress=controls.step,
        stopped=controls.stopped,
        bracket=controls.ask if bracket else None,
    )


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
