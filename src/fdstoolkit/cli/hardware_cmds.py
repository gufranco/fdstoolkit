from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Final

import typer

from fdstoolkit.build.calibration import (
    TRUSTED_DRIVE,
    CalibrationChoiceError,
    calibration_disk,
    check_write_choice,
)
from fdstoolkit.cli.common import (
    Family,
    ForceOption,
    JsonOption,
    RetriesOption,
    YesOption,
    container_of,
    decode_image,
    encode_image,
    fail,
    guard_output,
    logged,
    side_count,
    writer_for,
)
from fdstoolkit.codecs.container import Container
from fdstoolkit.core.disk import Disk
from fdstoolkit.doctor import CheckStatus, hardware_checks
from fdstoolkit.drive.captures import created_now, write_bundle
from fdstoolkit.drive.pulse import pulse_lines
from fdstoolkit.drive.recognition import rate_lines
from fdstoolkit.drive.recovery import recover
from fdstoolkit.edit.kiosk import KioskError, kiosk_target
from fdstoolkit.hardware.fdsstick import FdsStick, link_note, open_fdsstick
from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.hardware.session import (
    MAX_PASSES,
    DumpResult,
    Grade,
    LongSideError,
    Reading,
    SideFlipError,
    WriteRefusedError,
    read_disk,
)
from fdstoolkit.hardware.writing import WriteReport, refuse_long_sides, write_verified
from fdstoolkit.history.entries import drive_key, dump_entry, stamp_now
from fdstoolkit.report import as_json


def open_drive() -> FdsStick:
    try:
        return open_fdsstick()
    except HardwareFaultError as error:
        raise fail(str(error)) from error


STATUS_NOTE: Final = (
    "the stick reports nothing about the disk itself: not whether one is inserted, "
    "whether it is write protected, or whether the battery holds"
)


def prompter(*, yes: bool) -> Callable[[str], bool]:
    def ask(message: str) -> bool:
        if yes:
            typer.echo(message, err=True)
            return True
        return typer.confirm(message, err=True)

    return ask


def step(message: str) -> None:
    typer.echo(f"  {message}", err=True)


def status(
    *,
    json_output: JsonOption = False,
) -> None:
    checks = hardware_checks()
    ready = all(check.status is CheckStatus.OK for check in checks)
    if json_output:
        typer.echo(
            as_json(
                {
                    "ready": ready,
                    "checks": [
                        {"name": check.name, "status": str(check.status), "detail": check.detail}
                        for check in checks
                    ],
                }
            )
        )
        raise typer.Exit(code=0 if ready else 1)
    for check in checks:
        marker = "" if check.status is CheckStatus.OK else f" [{check.status}]"
        typer.echo(f"{check.name:<17} {check.detail}{marker}")
    typer.echo(STATUS_NOTE)
    raise typer.Exit(code=0 if ready else 1)


DumpOutputOption = Annotated[Path, typer.Option("-o", "--output", help="where to write the dump")]


ReadSidesOption = Annotated[
    int, typer.Option("--sides", parser=side_count, help="1 or 2 sides to read")
]


DumpPassesOption = Annotated[
    int, typer.Option("--passes", min=1, max=MAX_PASSES, help="read each side this often")
]


RawOption = Annotated[
    Path | None,
    typer.Option(
        "--raw", help="also keep every pulse capture the drive returned, with a manifest, here"
    ),
]


TurnedOption = Annotated[
    bool, typer.Option("--yes", help="assume the disk is turned over when asked")
]


@dataclass(frozen=True, slots=True)
class _DumpPlan:
    sides: int
    passes: int
    retries: int
    yes: bool
    raw: Path | None
    output: Path


def _read(drive: FdsStick, plan: _DumpPlan) -> Reading:
    try:
        return read_disk(
            drive,
            sides=plan.sides,
            passes=plan.passes,
            retries=plan.retries,
            flip=prompter(yes=plan.yes),
            progress=step,
        )
    except KeyboardInterrupt:
        message = "stopped on interrupt, nothing was written"
        raise _stopped(drive, plan.raw, plan.output, message) from None
    except (HardwareFaultError, WriteRefusedError, SideFlipError) as error:
        raise _stopped(drive, plan.raw, plan.output, str(error)) from error


@dataclass(frozen=True, slots=True)
class _Kept:
    grade: Grade
    result: DumpResult


def _kept_dump(drive: FdsStick, reading: Reading, output: Path, container: Container) -> _Kept:
    for line in reading.lines:
        typer.echo(line)
    outcome = recover(reading.result, drive.captures)
    result = outcome.result
    grade = reading.settled(result, changed=bool(outcome.recovered))
    data = encode_image(result.as_disk(), container)
    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes), grade {grade}")
    for line in outcome.lines:
        typer.echo(line)
    report_blocks(result)
    report_link(drive)
    return _Kept(grade=grade, result=result)


def dump(
    output: DumpOutputOption,
    *,
    sides: ReadSidesOption = 1,
    passes: DumpPassesOption = 1,
    retries: RetriesOption = 3,
    raw: RawOption = None,
    yes: TurnedOption = False,
    force: ForceOption = False,
) -> None:
    container = container_of(output)
    guard_output(output, force=force)
    plan = _DumpPlan(sides=sides, passes=passes, retries=retries, yes=yes, raw=raw, output=output)
    with closing(open_drive()) as drive:
        kept = _kept_dump(drive, _read(drive, plan), output, container)
        if raw is not None:
            keep_captures(drive, raw, image=output.name)
        entry = dump_entry(
            stamp_now(), kept.result, drive.captures, grade=kept.grade, drive=drive_key()
        )
        logged(entry)
        raise typer.Exit(code=0 if kept.grade is Grade.CLEAN else 1)


def report_link(drive: FdsStick) -> None:
    for line in (*pulse_lines(drive.pulse_findings, drive.captures), *rate_lines(drive.captures)):
        typer.echo(f"  {line}")
    note = link_note(drive.resyncs)
    if note:
        typer.echo(f"  {note}")


def _stopped(drive: FdsStick, raw: Path | None, output: Path, message: str) -> typer.Exit:
    report_link(drive)
    if raw is not None:
        keep_captures(drive, raw, image=output.name)
    return fail(message)


def report_blocks(result: DumpResult) -> None:
    for side in result.sides:
        for line in side.lines:
            typer.echo(f"  {line}")


def keep_captures(drive: FdsStick, directory: Path, *, image: str) -> None:
    captures = drive.captures
    if not captures:
        typer.echo("  the drive returned no pulse capture to keep")
        return
    written = write_bundle(directory, captures, image=image, created=created_now())
    typer.echo(
        f"  kept {len(captures)} capture(s) of packed pulse classes in {directory}, "
        f"described by {written[0].name}"
    )


def calibration_target(image: Path | None, *, calibration: bool, trusted_drive: bool) -> Disk:
    if calibration:
        for line in TRUSTED_DRIVE:
            typer.echo(line)
    try:
        check_write_choice(
            has_image=image is not None, calibration=calibration, trusted_drive=trusted_drive
        )
    except CalibrationChoiceError as error:
        hint = ". Pass --trusted-drive to give it" if calibration and not trusted_drive else ""
        message = f"{error}{hint}"
        raise fail(message) from error
    if image is None:
        return calibration_disk()
    disk, _, _, _ = decode_image(image)
    return disk


WrittenArgument = Annotated[Path | None, typer.Argument(help="the image to write to a disk")]


CalibrationOption = Annotated[
    bool, typer.Option("--calibration", help="write the calibration disk instead of an image")
]


TrustedOption = Annotated[
    bool,
    typer.Option(
        "--trusted-drive",
        help="confirm the drive in use is cleaned, aligned and at speed, as listed",
    ),
]


BackupOption = Annotated[
    Path | None, typer.Option("--backup", help="where to save the disk's current contents")
]


LongSideOption = Annotated[
    bool,
    typer.Option(
        "--long-side",
        help="write a side longer than any factory side, accepting that it may not fit",
    ),
]


@dataclass(frozen=True, slots=True)
class WritePlan:
    ask: Callable[[str], bool]
    backup: Path | None
    retries: int
    long_side: bool


def write_disk(drive: FdsStick, disk: Disk, plan: WritePlan) -> WriteReport:
    try:
        if not plan.long_side:
            refuse_long_sides(disk)
        return write_verified(
            drive,
            drive,
            disk,
            confirm=plan.ask,
            flip=plan.ask,
            progress=step,
            backup=None if plan.backup is None else writer_for(plan.backup),
            retries=plan.retries,
        )
    except KeyboardInterrupt:
        message = "stopped on interrupt, the disk may be half written, dump it before using it"
        raise fail(message) from None
    except LongSideError as error:
        message = f"{error}. Pass --long-side to write it anyway"
        raise fail(message) from error
    except (HardwareFaultError, WriteRefusedError, SideFlipError) as error:
        raise fail(str(error)) from error


def print_write(report: WriteReport) -> None:
    for line in report.lines:
        typer.echo(line)
    typer.echo(f"verified {report.verified}, grade {report.grade}")
    for note in report.notes:
        typer.echo(f"  {note}")


AsKioskOption = Annotated[
    bool, typer.Option("--as-kiosk", help="stamp the count, date and serial a kiosk did")
]
RewriteDateOption = Annotated[
    str | None, typer.Option("--rewrite-date", help="with --as-kiosk, the date, YYYY-MM-DD")
]


def _as_kiosk(disk: Disk, rewrite_date: str | None) -> Disk:
    try:
        return kiosk_target(disk, rewrite_date=rewrite_date, today=date.today())  # noqa: DTZ011
    except KioskError as error:
        raise fail(str(error)) from error


def write(
    image: WrittenArgument = None,
    *,
    calibration: CalibrationOption = False,
    trusted_drive: TrustedOption = False,
    backup: BackupOption = None,
    yes: YesOption = False,
    retries: RetriesOption = 3,
    long_side: LongSideOption = False,
    as_kiosk: AsKioskOption = False,
    rewrite_date: RewriteDateOption = None,
) -> None:
    disk = calibration_target(image, calibration=calibration, trusted_drive=trusted_drive)
    disk = _as_kiosk(disk, rewrite_date) if as_kiosk else disk
    plan = WritePlan(ask=prompter(yes=yes), backup=backup, retries=retries, long_side=long_side)
    with closing(open_drive()) as drive:
        report = write_disk(drive, disk, plan)
        print_write(report)
        raise typer.Exit(code=0 if report.verified else 1)


def register(app: typer.Typer) -> None:
    app.command(
        rich_help_panel=Family.HARDWARE,
        help=(
            "Report whether an FDSStick is attached, what it says about itself, "
            "and whether it opens."
        ),
    )(status)
    app.command(rich_help_panel=Family.HARDWARE, help="Dump a disk through the FDSStick.")(dump)
    app.command(
        rich_help_panel=Family.HARDWARE,
        help="Write an image, or the calibration disk, then read it back and compare.",
    )(write)
