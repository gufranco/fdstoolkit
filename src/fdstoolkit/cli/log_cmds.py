from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import Family, JsonOption, decode_image, fail
from fdstoolkit.history.logbook import LogbookError
from fdstoolkit.history.lookup import Subject, log_payload, look_up, subject_for
from fdstoolkit.history.trend import Trend, trend_lines
from fdstoolkit.report import as_json

LoggedArgument = Annotated[
    Path | None, typer.Argument(help="an image of the disk whose history to show")
]
DriveOption = Annotated[
    str | None,
    typer.Option("--drive", help="show the history of the drive with this label instead"),
]


def _subject(image: Path | None, drive: str | None) -> Subject:
    disk = None if image is None else decode_image(image)[0]
    try:
        return subject_for(disk, drive)
    except ValueError as error:
        raise fail(str(error)) from error


def _trend(subject: Subject) -> Trend:
    try:
        return look_up(subject)
    except LogbookError as error:
        raise fail(str(error)) from error


def log_command(
    image: LoggedArgument = None,
    *,
    drive: DriveOption = None,
    json_output: JsonOption = False,
) -> None:
    subject = _subject(image, drive)
    trend = _trend(subject)
    if json_output:
        typer.echo(as_json(log_payload(subject, trend)))
        return
    typer.echo(subject.title)
    for line in trend_lines(trend):
        typer.echo(line)


def register(app: typer.Typer) -> None:
    app.command(
        name="log",
        rich_help_panel=Family.CHECK,
        help="Show the logged dumps, grades and calibrations of a disk or a drive.",
    )(log_command)
