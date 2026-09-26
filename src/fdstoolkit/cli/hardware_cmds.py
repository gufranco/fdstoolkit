from __future__ import annotations

import webbrowser
from collections.abc import Callable
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
    container_of,
    decode_image,
    encode_image,
    fail,
    guard_output,
    writer_for,
)
from fdstoolkit.core.disk import SIDES_PER_DISK, Disk
from fdstoolkit.doctor import CheckStatus, hardware_checks
from fdstoolkit.drive.captures import created_now, write_bundle
from fdstoolkit.drive.recovery import recover
from fdstoolkit.hardware.fdsstick import FdsStick, open_fdsstick
from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.hardware.session import (
    MAX_PASSES,
    MAX_RETRIES,
    DumpResult,
    Grade,
    LongSideError,
    SideFlipError,
    WriteRefusedError,
    dump_repeated,
    refuse_long_sides,
    worst_grade,
    write_verified,
)
from fdstoolkit.hardware.session import dump as dump_disk
from fdstoolkit.quality.surface import (
    Finish,
    SurfacePlan,
    SurfaceReport,
    SurfaceTestRefusedError,
    surface_test,
)
from fdstoolkit.report import as_json

DEFAULT_SIDES: Final = 1


DEFAULT_PASSES: Final = 1


DEFAULT_RETRY_COUNT: Final = 3


UI_HINT: Final = (
    "this build carries no web interface, which a Homebrew install always does. "
    "Reinstall with: brew install gufranco/fdstoolkit/fdstoolkit"
)


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
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Report whether an FDSStick is attached, what it says about itself, and whether it opens."""
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


def dump(
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the dump")],
    *,
    sides: Annotated[
        int, typer.Option("--sides", min=1, max=SIDES_PER_DISK, help="1 or 2 sides to read")
    ] = 1,
    passes: Annotated[
        int, typer.Option("--passes", min=1, max=MAX_PASSES, help="read each side this often")
    ] = 1,
    retries: Annotated[
        int,
        typer.Option(
            "--retries",
            min=0,
            max=MAX_RETRIES,
            help="re-read a side with failed blocks up to this many more times",
        ),
    ] = 3,
    raw: Annotated[
        Path | None,
        typer.Option(
            "--raw", help="also keep every pulse capture the drive returned, with a manifest, here"
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="assume the disk is turned over when asked"),
    ] = False,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Dump a disk through the FDSStick."""
    container = container_of(output)
    guard_output(output, force=force)
    drive = open_drive()

    flip = prompter(yes=yes)

    try:
        if passes > 1:
            report = dump_repeated(
                drive,
                sides=sides,
                passes=passes,
                retries=retries,
                flip=flip,
                progress=step,
            )
            result = report.passes[0]
            grade = report.grade
            unsettled = Grade.UNSTABLE if report.unstable_blocks else Grade.CLEAN
            for side_index, block_index in report.unstable_blocks:
                typer.echo(f"side {side_index}: block {block_index} differs between passes")
        else:
            result = dump_disk(drive, sides=sides, retries=retries, flip=flip, progress=step)
            grade = result.grade
            unsettled = Grade.CLEAN
    except KeyboardInterrupt:
        message = "stopped on interrupt, nothing was written"
        raise fail(message) from None
    except (HardwareFaultError, WriteRefusedError, SideFlipError) as error:
        raise fail(str(error)) from error

    outcome = recover(result, drive.captures)
    result = outcome.result
    grade = worst_grade(result.grade, unsettled) if outcome.recovered else grade
    data = encode_image(result.as_disk(), container)
    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes), grade {grade}")
    for line in outcome.lines:
        typer.echo(line)
    report_blocks(result)
    if raw is not None:
        keep_captures(drive, raw, image=output.name)
    raise typer.Exit(code=0 if grade is Grade.CLEAN else 1)


def report_blocks(result: DumpResult) -> None:
    for side in result.sides:
        if side.marginal_blocks:
            typer.echo(
                f"  side {side.index}: {len(side.marginal_blocks)} block(s) only read clean on "
                "a re-read, so this disk is wearing"
            )
        if side.failed_blocks:
            typer.echo(
                f"  side {side.index}: {len(side.failed_blocks)} block(s) never read clean, "
                f"blocks {', '.join(str(index) for index in side.failed_blocks)}"
            )


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


def write(
    image: Annotated[Path | None, typer.Argument(help="the image to write to a disk")] = None,
    *,
    calibration: Annotated[
        bool,
        typer.Option("--calibration", help="write the calibration disk instead of an image"),
    ] = False,
    trusted_drive: Annotated[
        bool,
        typer.Option(
            "--trusted-drive",
            help="confirm the drive in use is cleaned, aligned and at speed, as listed",
        ),
    ] = False,
    backup: Annotated[
        Path | None,
        typer.Option("--backup", help="where to save the disk's current contents"),
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", help="answer the confirmation")] = False,
    retries: Annotated[
        int,
        typer.Option(
            "--retries",
            min=0,
            max=MAX_RETRIES,
            help="re-read a side with failed blocks up to this many more times",
        ),
    ] = 3,
    long_side: Annotated[
        bool,
        typer.Option(
            "--long-side",
            help="write a side longer than any factory side, accepting that it may not fit",
        ),
    ] = False,
) -> None:
    """Write an image, or the calibration disk, then read it back and compare."""
    disk = calibration_target(image, calibration=calibration, trusted_drive=trusted_drive)
    drive = open_drive()

    ask = prompter(yes=yes)

    try:
        if not long_side:
            refuse_long_sides(disk)
        report = write_verified(
            drive,
            drive,
            disk,
            confirm=ask,
            flip=ask,
            progress=step,
            backup=None if backup is None else writer_for(backup),
            retries=retries,
        )
    except KeyboardInterrupt:
        message = "stopped on interrupt, the disk may be half written, dump it before using it"
        raise fail(message) from None
    except LongSideError as error:
        message = f"{error}. Pass --long-side to write it anyway"
        raise fail(message) from error
    except (HardwareFaultError, WriteRefusedError, SideFlipError) as error:
        raise fail(str(error)) from error

    for line in report.lines:
        typer.echo(line)
    typer.echo(f"verified {report.verified}, grade {report.grade}")
    for note in report.notes:
        typer.echo(f"  {note}")
    raise typer.Exit(code=0 if report.verified else 1)


def surface(
    *,
    sides: Annotated[
        int, typer.Option("--sides", min=1, max=SIDES_PER_DISK, help="1 or 2 sides to test")
    ] = 1,
    backup: Annotated[
        Path | None,
        typer.Option("--backup", help="where to save the disk's current contents"),
    ] = None,
    passes: Annotated[
        int,
        typer.Option(
            "--passes", min=1, max=MAX_PASSES, help="how many times to run the pattern cycle"
        ),
    ] = 1,
    quick: Annotated[
        bool,
        typer.Option("--quick", help="write one 4 KiB file per side instead of filling it"),
    ] = False,
    finish: Annotated[
        Finish,
        typer.Option("--finish", help="what to leave on the disk when the test ends"),
    ] = Finish.LEAVE,
    yes: Annotated[bool, typer.Option("--yes", help="answer the confirmation")] = False,
) -> None:
    """Write and read back every pulse length to grade a scratch disk."""
    drive = open_drive()

    ask = prompter(yes=yes)

    sink = None if backup is None else writer_for(backup)

    try:
        report = surface_test(
            drive,
            drive,
            sides=sides,
            confirm=ask,
            flip=ask,
            progress=step,
            backup=sink,
            plan=SurfacePlan(rounds=passes, fill=not quick, finish=finish),
        )
    except (HardwareFaultError, WriteRefusedError, SideFlipError, SurfaceTestRefusedError) as error:
        raise fail(str(error)) from error

    report_surface(report)
    typer.echo(f"grade {report.grade}")
    raise typer.Exit(code=0 if report.passed else 1)


def report_surface(report: SurfaceReport) -> None:
    typer.echo(
        f"{report.data_bytes} data bytes per side, {report.coverage:.1%} of the most any "
        f"measured factory side carries, {len(report.passes)} pattern pass(es) run",
    )
    for entry in report.passes:
        state = "held" if entry.verified else "did not hold"
        typer.echo(f"side {entry.side} pass {entry.round} pattern {entry.pattern}: {state}")
    if report.pulse_summary:
        typer.echo(report.pulse_summary)

    if report.hard_blocks:
        typer.echo(
            f"{len(report.hard_blocks)} block(s) failed on more than one pattern, "
            "which is the surface itself",
        )
    if report.transient_blocks:
        typer.echo(
            f"{len(report.transient_blocks)} block(s) failed once, marginal rather than dead",
        )
    if report.recovered_blocks:
        typer.echo(
            f"{len(report.recovered_blocks)} block(s) failed early and read clean after, "
            "so rewriting refreshed them",
        )

    if report.stopped is not None:
        typer.echo(f"stopped early: {report.stopped.value}")
    if report.refusal:
        typer.echo(f"  {report.refusal}")
    _report_finish(report)


def _report_finish(report: SurfaceReport) -> None:
    if report.finish is not Finish.LEAVE and not report.finish_ran:
        typer.echo("the finish was skipped because the test stopped early")
    elif report.finish is not Finish.LEAVE:
        left = (
            "formatted as it leaves the kiosk"
            if report.finish is Finish.BLANK
            else "erased, with nothing the adapter can read"
        )
        state = "verified" if report.finish_verified else "which did not verify"
        typer.echo(f"left the disk {left}, {state}")
    if report.finish_problem:
        typer.echo(f"  {report.finish_problem}")


def web_server() -> tuple[Callable[..., None], Callable[[], object]]:
    import uvicorn  # noqa: PLC0415

    from fdstoolkit.ui.app import create_app  # noqa: PLC0415

    return uvicorn.run, create_app


def _require_web() -> tuple[Callable[..., None], Callable[[], object]]:
    try:
        return web_server()
    except ImportError as error:
        raise fail(UI_HINT) from error


LOOPBACK: Final = frozenset({"127.0.0.1", "::1", "localhost"})

PUBLISHED_HINT: Final = (
    "anyone who can reach this machine on that port can drive it, and there is no password. "
    "Bind 127.0.0.1 unless you meant to publish it"
)


def _start_web(*, host: str, port: int, open_browser: bool) -> None:
    run, build = _require_web()
    address = f"http://{host}:{port}"
    if host in LOOPBACK:
        typer.echo(f"serving on {address}, and nothing leaves this machine")
    else:
        typer.echo(f"serving on {address}")
        typer.echo(PUBLISHED_HINT)
    if open_browser:
        webbrowser.open(address)
    run(build(), host=host, port=port)


def web(
    *,
    host: Annotated[str, typer.Option("--host", help="which interface to bind")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8000,
    no_open: Annotated[
        bool,
        typer.Option("--no-open", help="start the server without opening a browser"),
    ] = False,
) -> None:
    """Open the local web interface, which reports exactly what these commands report."""
    _start_web(host=host, port=port, open_browser=not no_open)


def register(app: typer.Typer) -> None:
    app.command(rich_help_panel=Family.HARDWARE)(status)
    app.command(rich_help_panel=Family.HARDWARE)(dump)
    app.command(rich_help_panel=Family.HARDWARE)(write)
    app.command(rich_help_panel=Family.HARDWARE)(surface)
    app.command()(web)
