from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import Family, JsonOption, fail, load_captures
from fdstoolkit.core.disk import SIDES_PER_DISK
from fdstoolkit.drive.track import Track, track_lines, track_of, track_payload
from fdstoolkit.report import as_json

BundleArgument = Annotated[Path, typer.Argument(help="the capture bundle a dump --raw kept")]
TrackSideOption = Annotated[
    int,
    typer.Option("--side", min=0, max=SIDES_PER_DISK - 1, help="which side of the bundle to draw"),
]


def _track(bundle: Path, side: int) -> Track:
    try:
        return track_of(load_captures(bundle).of_side(side), side)
    except ValueError as error:
        raise fail(str(error)) from error


def track(
    bundle: BundleArgument, *, side: TrackSideOption = 0, json_output: JsonOption = False
) -> None:
    found = _track(bundle, side)
    if json_output:
        typer.echo(as_json(track_payload(found)))
    else:
        for line in track_lines(found):
            typer.echo(line)
    raise typer.Exit(code=1 if found.weak else 0)


def register(app: typer.Typer) -> None:
    app.command(
        rich_help_panel=Family.CHECK,
        help="Lay a side out block by block from saved captures, marking the weak blocks.",
    )(track)
