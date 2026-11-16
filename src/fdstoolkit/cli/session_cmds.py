from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import Family, JsonOption, RetriesOption, decode_image, fail, logged
from fdstoolkit.cli.hardware_cmds import open_drive, step
from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.hardware.session import DumpResult, SideFlipError, WriteRefusedError, read_disk
from fdstoolkit.history.checks import check_entry, drift_lines, drift_of, drift_payload
from fdstoolkit.history.entries import drive_key, stamp_now
from fdstoolkit.history.logbook import Entry, LogbookError, history, logbook_path
from fdstoolkit.report import as_json

ReferenceOption = Annotated[
    Path | None,
    typer.Option(
        "--reference",
        help="an image of the reference disk in the drive, dumped by a drive you trust",
    ),
]


def _earlier(drive: str) -> tuple[Entry, ...]:
    try:
        return history(logbook_path(), drive=drive)
    except LogbookError as error:
        raise fail(str(error)) from error


def _read_reference(retries: int) -> DumpResult:
    with closing(open_drive()) as drive:
        try:
            return read_disk(drive, sides=1, passes=1, retries=retries, progress=step).result
        except (HardwareFaultError, WriteRefusedError, SideFlipError) as error:
            raise fail(str(error)) from error


def session_command(
    *,
    reference: ReferenceOption = None,
    retries: RetriesOption = 3,
    json_output: JsonOption = False,
) -> None:
    wanted = None if reference is None else decode_image(reference)[0]
    key = drive_key()
    earlier = _earlier(key.drive)
    entry = check_entry(stamp_now(), _read_reference(retries), wanted, key)
    logged(entry)
    drift = drift_of(earlier, entry)
    if json_output:
        typer.echo(as_json(drift_payload(drift)))
    else:
        for line in drift_lines(drift):
            typer.echo(line)
    raise typer.Exit(code=1 if drift.moved else 0)


def register(app: typer.Typer) -> None:
    app.command(
        name="session",
        rich_help_panel=Family.HARDWARE,
        help="Read a reference disk and warn when the drive moved since its last check.",
    )(session_command)
