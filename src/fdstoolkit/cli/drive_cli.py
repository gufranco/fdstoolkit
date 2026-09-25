from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import Family, decode_image, fail, load_captures
from fdstoolkit.cli.hardware_cmds import open_drive, prompter, step
from fdstoolkit.core.disk import SIDES_PER_DISK, Side
from fdstoolkit.drive.monitor import (
    DEFAULT_READS,
    MAX_READS,
    NOT_THIS_DRIVE,
    Calibration,
    Mode,
    RawReader,
    Replay,
    calibrate,
)
from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.report import as_json


def reference_side(path: Path | None, side: int) -> Side | None:
    if path is None:
        return None
    disk, _, _, _ = decode_image(path)
    if side >= disk.side_count:
        message = f"{path.name} has {disk.side_count} side(s), so it has no side {side}"
        raise fail(message)
    return disk.sides[side]


def _replay(path: Path, side: int) -> Replay:
    saved = load_captures(path).of_side(side)[:MAX_READS]
    if not saved:
        message = f"{path.name} holds no read of side {side}"
        raise fail(message)
    return Replay(saved)


def _live(
    drive: RawReader, *, mode: Mode, passes: int, wanted: Side | None, bracket: bool
) -> Calibration:
    try:
        return calibrate(
            drive,
            mode=mode,
            reads=passes,
            reference=wanted,
            progress=step,
            bracket=prompter(yes=False) if bracket else None,
        )
    except HardwareFaultError as error:
        raise fail(str(error)) from error


def calibration_json(result: Calibration) -> dict[str, object]:
    return {
        "mode": result.mode.value,
        "clean": result.clean,
        "headline": result.headline,
        "reads": result.rows(),
    }


def calibrate_command(
    mode: Annotated[Mode, typer.Argument(help="speed for the motor, head for the head and hub")],
    *,
    reference: Annotated[
        Path | None,
        typer.Option(
            "--reference",
            help="an image of the disk in the drive, dumped by a drive you trust",
        ),
    ] = None,
    side: Annotated[
        int,
        typer.Option(
            "--side",
            min=0,
            max=SIDES_PER_DISK - 1,
            help="which side of the reference is turned down, toward the head",
        ),
    ] = 0,
    passes: Annotated[
        int,
        typer.Option("--passes", min=1, max=MAX_READS, help="read the side this many times"),
    ] = DEFAULT_READS,
    bracket: Annotated[
        bool,
        typer.Option(
            "--bracket",
            help="ask for one small step between reads and find the middle of the range that reads",
        ),
    ] = False,
    captures: Annotated[
        Path | None,
        typer.Option(
            "--captures", help="replay the reads a dump --raw kept instead of reading the drive"
        ),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Read a side over and over while you adjust the drive, and say what each read shows."""
    wanted = reference_side(reference, side)
    if captures is not None:
        replay = _replay(captures, side)
        result = calibrate(
            replay, mode=mode, reads=len(replay.captures), reference=wanted, progress=step
        )
    else:
        typer.echo(NOT_THIS_DRIVE)
        drive = open_drive()
        try:
            result = _live(drive, mode=mode, passes=passes, wanted=wanted, bracket=bracket)
        finally:
            drive.close()

    if json_output:
        typer.echo(as_json(calibration_json(result)))
    else:
        typer.echo(result.headline)
    raise typer.Exit(code=0 if result.clean else 1)


def register(app: typer.Typer) -> None:
    app.command(name="calibrate", rich_help_panel=Family.HARDWARE)(calibrate_command)
