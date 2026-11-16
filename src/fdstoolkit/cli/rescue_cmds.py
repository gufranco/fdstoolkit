from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import (
    Family,
    ForceOption,
    container_of,
    encode_image,
    fail,
    guard_output,
)
from fdstoolkit.cli.hardware_cmds import open_drive, step
from fdstoolkit.core.disk import SIDES_PER_DISK
from fdstoolkit.drive.rescue import (
    RescueError,
    RescueState,
    load_folder,
    progress_of,
    read_into,
    save_folder,
    side_settled,
)
from fdstoolkit.hardware.fdsstick import FdsStick
from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.hardware.session import MAX_PASSES

FolderArgument = Annotated[
    Path, typer.Argument(help="the rescue folder, made on the first run and kept between runs")
]
RescueOutputOption = Annotated[
    Path, typer.Option("-o", "--output", help="where to write the image once every block settles")
]
RescueSideOption = Annotated[
    int,
    typer.Option(
        "--side",
        min=0,
        max=SIDES_PER_DISK - 1,
        help="which side is face down in the drive, its label facing up",
    ),
]
RescuePassesOption = Annotated[
    int, typer.Option("--passes", min=1, max=MAX_PASSES, help="how many reads this run adds")
]


def _loaded(folder: Path) -> RescueState:
    try:
        return load_folder(folder)
    except RescueError as error:
        raise fail(str(error)) from error


def _added(drive: FdsStick, folder: Path, state: RescueState, side: int) -> RescueState:
    step(f"reading side {side}, read {state.reads_of(side) + 1} of the rescue")
    try:
        grown = read_into(state, drive, side)
    except RescueError as error:
        raise fail(str(error)) from error
    save_folder(folder, grown)
    return grown


def _stopped(folder: Path, state: RescueState, side: int, message: str) -> typer.Exit:
    kept = f"{state.reads_of(side)} read(s) of side {side} are kept in {folder}"
    return fail(f"{message}; {kept}")


def _gathered(folder: Path, state: RescueState, side: int, passes: int) -> RescueState:
    with closing(open_drive()) as drive:
        current = state
        try:
            for _ in range(passes):
                current = _added(drive, folder, current, side)
                if side_settled(current, side):
                    break
        except KeyboardInterrupt:
            raise _stopped(folder, current, side, "stopped") from None
        except HardwareFaultError as error:
            raise _stopped(folder, current, side, str(error)) from error
        return current


def rescue(
    folder: FolderArgument,
    *,
    output: RescueOutputOption,
    side: RescueSideOption = 0,
    passes: RescuePassesOption = 3,
    force: ForceOption = False,
) -> None:
    container = container_of(output)
    guard_output(output, force=force)
    state = _gathered(folder, _loaded(folder), side, passes)
    progress = progress_of(state)
    for line in progress.lines:
        typer.echo(line.strip())
    if not progress.settled:
        typer.echo(f"run rescue again to add reads; every read so far is kept in {folder}")
        raise typer.Exit(code=1)
    data = encode_image(progress.disk, container)
    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes)")


def register(app: typer.Typer) -> None:
    app.command(
        rich_help_panel=Family.HARDWARE,
        help="Read a failing disk over several sessions until every block settles.",
    )(rescue)
