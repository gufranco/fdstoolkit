from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import Family, JsonOption, decode_image, fail, load_captures
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
from fdstoolkit.drive.timing import Timing, TimingReader
from fdstoolkit.hardware.fdsstick import FdsStick
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


def calibration_json(result: Calibration, timings: Sequence[Timing] = ()) -> dict[str, object]:
    return {
        "mode": result.mode.value,
        "clean": result.clean,
        "headline": result.headline,
        "spread": result.spread,
        "reads": result.rows(),
        "timing": [timing.as_dict() for timing in timings],
    }


ModeArgument = Annotated[
    Mode, typer.Argument(help="speed for the motor, head for the head and hub")
]
ReferenceOption = Annotated[
    Path | None,
    typer.Option(
        "--reference", help="an image of the disk in the drive, dumped by a drive you trust"
    ),
]
SideOption = Annotated[
    int,
    typer.Option(
        "--side",
        min=0,
        max=SIDES_PER_DISK - 1,
        help="which side of the reference is in the drive, its label facing up",
    ),
]
PassesOption = Annotated[
    int, typer.Option("--passes", min=1, max=MAX_READS, help="read the side this many times")
]
BracketOption = Annotated[
    bool,
    typer.Option(
        "--bracket",
        help="ask for one small step between reads and find the middle of the range that reads",
    ),
]
ReplayOption = Annotated[
    Path | None,
    typer.Option(
        "--captures", help="replay the reads a dump --raw kept instead of reading the drive"
    ),
]


def _timed(
    drive: FdsStick, *, mode: Mode, passes: int, wanted: Side | None, bracket: bool
) -> tuple[Calibration, tuple[Timing, ...]]:
    timed = TimingReader(drive, note=step)
    try:
        result = _live(timed, mode=mode, passes=passes, wanted=wanted, bracket=bracket)
    finally:
        drive.close()
    return result, tuple(timed.timings)


def _print_calibration(
    result: Calibration, timings: tuple[Timing, ...], *, json_output: bool
) -> None:
    if json_output:
        typer.echo(as_json(calibration_json(result, timings)))
    else:
        typer.echo(result.headline)


def calibrate_command(
    mode: ModeArgument,
    *,
    reference: ReferenceOption = None,
    side: SideOption = 0,
    passes: PassesOption = DEFAULT_READS,
    bracket: BracketOption = False,
    captures: ReplayOption = None,
    json_output: JsonOption = False,
) -> None:
    wanted = reference_side(reference, side)
    if captures is not None:
        replay = _replay(captures, side)
        reads = len(replay.captures)
        result = calibrate(replay, mode=mode, reads=reads, reference=wanted, progress=step)
        timings: tuple[Timing, ...] = ()
    else:
        typer.echo(NOT_THIS_DRIVE, err=True)
        drive = open_drive()
        result, timings = _timed(drive, mode=mode, passes=passes, wanted=wanted, bracket=bracket)
    _print_calibration(result, timings, json_output=json_output)
    raise typer.Exit(code=0 if result.clean else 1)


def register(app: typer.Typer) -> None:
    app.command(
        name="calibrate",
        rich_help_panel=Family.HARDWARE,
        help="Read a side over and over while you adjust the drive, and say what each read shows.",
    )(calibrate_command)
