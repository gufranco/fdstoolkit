from __future__ import annotations

import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Final

import typer

from fdstoolkit.cli.common import (
    Family,
    decode_image,
    fail,
    guard_output,
    writer_for,
)
from fdstoolkit.codecs import fds
from fdstoolkit.core.disk import SIDES_PER_DISK
from fdstoolkit.doctor import CheckStatus, hardware_checks
from fdstoolkit.hardware.fdsstick import FdsStick, open_fdsstick
from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.hardware.session import (
    MAX_PASSES,
    MAX_RETRIES,
    DumpResult,
    Grade,
    SideFlipError,
    WriteRefusedError,
    dump_repeated,
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
        typer.Option("--raw", help="also keep every pulse capture the drive returned, here"),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="assume the disk is turned over when asked"),
    ] = False,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Dump a disk through the FDSStick."""
    guard_output(output, force=force)
    drive = open_drive()

    def flip(message: str) -> bool:
        if yes:
            typer.echo(message)
            return True
        return typer.confirm(message)

    try:
        if passes > 1:
            report = dump_repeated(
                drive,
                sides=sides,
                passes=passes,
                retries=retries,
                flip=flip,
            )
            result = report.passes[0]
            grade = report.grade
            for side_index, block_index in report.unstable_blocks:
                typer.echo(f"side {side_index}: block {block_index} differs between passes")
        else:
            result = dump_disk(drive, sides=sides, retries=retries, flip=flip)
            grade = result.grade
    except KeyboardInterrupt:
        message = "stopped on interrupt, nothing was written"
        raise fail(message) from None
    except (HardwareFaultError, WriteRefusedError, SideFlipError) as error:
        raise fail(str(error)) from error

    data, _ = fds.encode(result.as_disk(), headered=False)
    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes), grade {grade}")
    report_blocks(result)
    if raw is not None:
        keep_captures(drive, raw, stem=output.stem)
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


def keep_captures(drive: FdsStick, directory: Path, *, stem: str) -> None:
    captures = drive.captures
    if not captures:
        typer.echo("  the drive returned no pulse capture to keep")
        return
    suffix = "raw03"
    kind = "packed pulse classes"
    directory.mkdir(parents=True, exist_ok=True)
    for index, capture in enumerate(captures, start=1):
        target = directory / f"{stem}.read{index:02d}.{suffix}"
        target.write_bytes(capture)
        typer.echo(f"  kept {target} ({len(capture)} bytes of {kind})")


def write(
    image: Annotated[Path, typer.Argument(help="the image to write to a disk")],
    *,
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
) -> None:
    """Write an image to a disk, then read it back and compare."""
    disk, _, _, _ = decode_image(image)
    drive = open_drive()

    def confirm(message: str) -> bool:
        if yes:
            return True
        return typer.confirm(message)

    try:
        report = write_verified(
            drive,
            drive,
            disk,
            confirm=confirm,
            backup=None if backup is None else writer_for(backup),
            retries=retries,
        )
    except KeyboardInterrupt:
        message = "stopped on interrupt, the disk may be half written, dump it before using it"
        raise fail(message) from None
    except (HardwareFaultError, WriteRefusedError) as error:
        raise fail(str(error)) from error

    for side_index, block_index in report.mismatched_blocks:
        typer.echo(f"side {side_index}: block {block_index} did not read back as written")
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
    """Write and read back complementary patterns to grade a scratch disk."""
    drive = open_drive()

    def confirm(message: str) -> bool:
        if yes:
            return True
        return typer.confirm(message)

    sink = None if backup is None else writer_for(backup)

    try:
        report = surface_test(
            drive,
            drive,
            sides=sides,
            confirm=confirm,
            backup=sink,
            plan=SurfacePlan(rounds=passes, fill=not quick, finish=finish),
        )
    except (HardwareFaultError, WriteRefusedError, SurfaceTestRefusedError) as error:
        raise fail(str(error)) from error

    report_surface(report)
    typer.echo(f"grade {report.grade}")
    raise typer.Exit(code=0 if report.passed else 1)


def report_surface(report: SurfaceReport) -> None:
    typer.echo(
        f"{report.data_bytes} data bytes per side, {report.coverage:.1%} of the physical track, "
        f"{len(report.passes)} pattern pass(es) run",
    )
    for entry in report.passes:
        state = "held" if entry.verified else "did not hold"
        typer.echo(f"pass {entry.round} pattern {entry.pattern:#04x}: {state}")

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
