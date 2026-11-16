from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import Family, JsonOption, fail, load_captures
from fdstoolkit.drive.triage import Triage, triage, triage_lines, triage_payload
from fdstoolkit.report import as_json

BundlesArgument = Annotated[
    list[Path], typer.Argument(help="the capture bundles of two or more disks read in one drive")
]


def _triaged(bundles: list[Path]) -> Triage:
    loaded = {str(path): load_captures(path) for path in bundles}
    try:
        return triage(loaded)
    except ValueError as error:
        raise fail(str(error)) from error


def triage_command(bundles: BundlesArgument, *, json_output: JsonOption = False) -> None:
    found = _triaged(bundles)
    if json_output:
        typer.echo(as_json(triage_payload(found)))
    else:
        for line in triage_lines(found):
            typer.echo(line)
    raise typer.Exit(code=1 if found.drive_fails else 0)


def register(app: typer.Typer) -> None:
    app.command(
        name="triage",
        rich_help_panel=Family.CHECK,
        help="Say, by position along the side, whether failures belong to the drive or a disk.",
    )(triage_command)
