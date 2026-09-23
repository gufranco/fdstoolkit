from __future__ import annotations

import webbrowser
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final

import typer

from fdstoolkit.cli.common import (
    decode_image,
    fail,
    guard_output,
    writer_for,
)
from fdstoolkit.codecs import fds
from fdstoolkit.doctor import CheckStatus, diagnose
from fdstoolkit.hardware.fdsstick import FdsStick, open_fdsstick
from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.hardware.session import (
    Grade,
    SideFlipError,
    WriteRefusedError,
    dump_repeated,
    write_verified,
)
from fdstoolkit.hardware.session import dump as dump_disk
from fdstoolkit.hardware.simulation import CaptureMode, SimulatedDrive
from fdstoolkit.quality.surface import (
    Finish,
    SurfacePlan,
    SurfaceTestRefusedError,
    surface_test,
)
from fdstoolkit.submit.log import load_log, log_of
from fdstoolkit.submit.report import submission_for


class Backend(StrEnum):
    SIMULATION = "simulation"
    FDSSTICK = "fdsstick"
    DUMPER = "dumper"


DEFAULT_SIDES: Final = 1


DEFAULT_PASSES: Final = 1


DEFAULT_RETRY_COUNT: Final = 3


UI_HINT: Final = (
    "this build carries no web interface, which a Homebrew install always does. "
    "Reinstall with: brew install gufranco/fdstoolkit/fdstoolkit"
)


def _dump_settings(*, sides: int, passes: int, retries: int) -> dict[str, object]:
    chosen: dict[str, object] = {}
    if sides != DEFAULT_SIDES:
        chosen["sides"] = sides
    if passes != DEFAULT_PASSES:
        chosen["passes"] = passes
    if retries != DEFAULT_RETRY_COUNT:
        chosen["retries"] = retries
    return chosen


def device_line(drive: object) -> str | None:
    if isinstance(drive, SimulatedDrive):
        return None
    report = diagnose()
    for check in report.checks:
        if check.name == "fdsstick" and check.status is CheckStatus.OK:
            return check.detail
    return None


def open_drive(
    backend: Backend,
    source: Path | None,
    rate: float | None = None,
    *,
    assume_writable: bool = False,
) -> SimulatedDrive | FdsStick:
    if backend is Backend.DUMPER:
        message = (
            "the Famicom Dumper backend needs a serial link, which this build does not open yet. "
            "Use --backend fdsstick, or drive it from the library with your own link"
        )
        raise fail(message)
    if backend is Backend.FDSSTICK:
        try:
            return open_fdsstick(assume_writable=assume_writable)
        except HardwareFaultError as error:
            raise fail(str(error)) from error
    if source is None:
        message = "the simulated backend needs --source naming an image to stand in for the disk"
        raise fail(message)
    disk, _, _, _ = decode_image(source)
    if rate is None:
        return SimulatedDrive(disk)
    if rate <= 0:
        message = "a simulated bit rate is positive"
        raise fail(message)
    return SimulatedDrive(disk, capture_mode=CaptureMode.TIMING, bit_rate_hz=rate)


def dump(
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the dump")],
    *,
    source: Annotated[
        Path | None,
        typer.Option("--source", help="image the simulated drive holds"),
    ] = None,
    backend: Annotated[
        Backend, typer.Option("--backend", help="which drive to use")
    ] = Backend.SIMULATION,
    sides: Annotated[int, typer.Option("--sides", min=1, max=8, help="sides to read")] = 1,
    passes: Annotated[int, typer.Option("--passes", min=1, help="read each side this often")] = 1,
    retries: Annotated[int, typer.Option("--retries", min=1, help="retries per block")] = 3,
    raw: Annotated[
        Path | None,
        typer.Option("--raw", help="also keep every pulse capture the drive returned, here"),
    ] = None,
    simulated_rate: Annotated[
        float | None,
        typer.Option(
            "--simulated-rate",
            help="make the simulated drive emit timing captures at this bit rate",
        ),
    ] = None,
    log: Annotated[
        Path | None,
        typer.Option("--log", help="write a record of how this dump was taken, for submission"),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="assume the disk is turned over when asked"),
    ] = False,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Dump a disk through a drive backend."""
    guard_output(output, force=force)
    drive = open_drive(backend, source, simulated_rate)

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
    if log is not None:
        record = log_of(
            result,
            backend=str(backend),
            device=device_line(drive),
            settings=_dump_settings(sides=sides, passes=passes, retries=retries),
            simulated=isinstance(drive, SimulatedDrive),
        )
        log.write_text(record.as_json(), encoding="utf-8")
        typer.echo(f"wrote {log} ({len(record.retried_blocks)} retried block(s) recorded)")
    if raw is not None:
        keep_captures(drive, raw, stem=output.stem)
    raise typer.Exit(code=0 if grade is Grade.CLEAN else 1)


def keep_captures(drive: SimulatedDrive | FdsStick, directory: Path, *, stem: str) -> None:
    captures = drive.captures
    if not captures:
        typer.echo("  the drive returned no pulse capture to keep")
        return
    timing = isinstance(drive, SimulatedDrive) and drive.capture_mode is CaptureMode.TIMING
    suffix = "counts" if timing else "raw03"
    kind = "interval counts" if timing else "packed pulse classes"
    directory.mkdir(parents=True, exist_ok=True)
    for index, capture in enumerate(captures, start=1):
        target = directory / f"{stem}.read{index:02d}.{suffix}"
        target.write_bytes(capture)
        typer.echo(f"  kept {target} ({len(capture)} bytes of {kind})")


def write(
    image: Annotated[Path, typer.Argument(help="the image to write to a disk")],
    *,
    source: Annotated[
        Path | None,
        typer.Option("--source", help="image the simulated drive holds"),
    ] = None,
    backend: Annotated[
        Backend, typer.Option("--backend", help="which drive to use")
    ] = Backend.SIMULATION,
    backup: Annotated[
        Path | None,
        typer.Option("--backup", help="where to save the disk's current contents"),
    ] = None,
    assume_writable: Annotated[
        bool,
        typer.Option(
            "--assume-writable",
            help="proceed when the drive cannot report whether the disk is protected",
        ),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="answer the confirmation")] = False,
    retries: Annotated[int, typer.Option("--retries", min=1, help="retries per block")] = 3,
) -> None:
    """Write an image to a disk, then read it back and compare."""
    disk, _, _, _ = decode_image(image)
    drive = open_drive(backend, source, assume_writable=assume_writable)

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
    source: Annotated[
        Path | None,
        typer.Option("--source", help="image the simulated drive holds"),
    ] = None,
    backend: Annotated[
        Backend,
        typer.Option("--backend", help="which drive to use"),
    ] = Backend.SIMULATION,
    sides: Annotated[int, typer.Option("--sides", min=1, max=8, help="sides to test")] = 1,
    backup: Annotated[
        Path | None,
        typer.Option("--backup", help="where to save the disk's current contents"),
    ] = None,
    passes: Annotated[
        int,
        typer.Option("--passes", min=1, max=64, help="how many times to run the pattern cycle"),
    ] = 1,
    quick: Annotated[
        bool,
        typer.Option("--quick", help="write one 4 KiB file per side instead of filling it"),
    ] = False,
    finish: Annotated[
        Finish,
        typer.Option("--finish", help="what to leave on the disk when the test ends"),
    ] = Finish.LEAVE,
    assume_writable: Annotated[
        bool,
        typer.Option(
            "--assume-writable",
            help="proceed when the drive cannot report whether the disk is protected",
        ),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="answer the confirmation")] = False,
) -> None:
    """Write and read back complementary patterns to grade a scratch disk."""
    drive = open_drive(backend, source, assume_writable=assume_writable)

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

    typer.echo(
        f"{report.data_bytes} data bytes per side, {report.coverage:.1%} of the physical track, "
        f"{passes} pass(es) of 4 patterns",
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

    if report.finish is not Finish.LEAVE:
        left = (
            "formatted as it leaves the kiosk"
            if report.finish is Finish.BLANK
            else "erased, with nothing the adapter can read"
        )
        state = "verified" if report.finish_verified else "which did not verify"
        typer.echo(f"left the disk {left}, {state}")

    typer.echo(f"grade {report.grade}")
    ok = report.grade is Grade.CLEAN and report.finish_verified
    raise typer.Exit(code=0 if ok else 1)


def submit(
    image: Annotated[Path, typer.Argument(help="the image that was dumped")],
    *,
    log: Annotated[Path, typer.Option("--log", help="the log that dump wrote")],
    dumper: Annotated[str, typer.Option("--dumper", help="who took the dump")],
    affiliation: Annotated[
        str,
        typer.Option("--affiliation", help="a group to credit, if any"),
    ] = "",
    photo: Annotated[
        list[Path] | None,
        typer.Option("--photo", help="a photograph to cite, repeatable"),
    ] = None,
    also: Annotated[
        list[Path] | None,
        typer.Option("--also", help="another file to hash into the submission, repeatable"),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("-o", "--output", help="write the submission here instead of printing it"),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Assemble the submission a preservation project asks for."""
    if not image.is_file():
        message = f"file not found: {image}"
        raise fail(message)
    if not log.is_file():
        message = f"file not found: {log}"
        raise fail(message)
    if output is not None:
        guard_output(output, force=force)

    try:
        record = load_log(log.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        message = f"could not read {log}: {error}"
        raise fail(message) from error

    extra: dict[str, bytes] = {}
    for path in also or []:
        if not path.is_file():
            message = f"file not found: {path}"
            raise fail(message)
        extra[path.name] = path.read_bytes()

    try:
        report = submission_for(
            image.read_bytes(),
            name=image.name,
            log=record,
            dumper=dumper,
            affiliation=affiliation,
            evidence=tuple(str(path) for path in photo or []),
            extra=extra,
        )
    except ValueError as error:
        raise fail(str(error)) from error

    text = report.render()
    if output is None:
        typer.echo(text, nl=False)
    else:
        output.write_text(text, encoding="utf-8")
        typer.echo(f"wrote {output} ({len(report.files)} file(s) hashed)")
    raise typer.Exit(code=0 if not report.missing_evidence else 1)


def web_server() -> tuple[Callable[..., None], Callable[[], object]]:
    import uvicorn  # noqa: PLC0415

    from fdstoolkit.ui.app import create_app  # noqa: PLC0415

    return uvicorn.run, create_app


def _require_web() -> tuple[Callable[..., None], Callable[[], object]]:
    try:
        return web_server()
    except ImportError as error:
        raise fail(UI_HINT) from error


def _start_web(*, host: str, port: int, open_browser: bool) -> None:
    run, build = _require_web()
    address = f"http://{host}:{port}"
    typer.echo(f"serving on {address}, and nothing leaves this machine")
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
    app.command()(dump)
    app.command()(write)
    app.command()(surface)
    app.command()(submit)
    app.command()(web)
