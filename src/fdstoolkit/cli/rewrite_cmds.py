from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Annotated, Final

import typer

from fdstoolkit.cli.common import Family, RetriesOption, YesOption, decode_image, fail, side_count
from fdstoolkit.cli.hardware_cmds import (
    BackupOption,
    WritePlan,
    open_drive,
    prompter,
    step,
    write_disk,
)
from fdstoolkit.hardware.duplicate import duplicate, duplicate_lines
from fdstoolkit.hardware.session import LongSideError
from fdstoolkit.hardware.writing import WriteReport, refuse_long_sides
from fdstoolkit.quality.surface_disks import erased_disk

ERASED: Final = "every side reads back with no block"
LEFT_BEHIND: Final = "the erase left blocks behind, listed above"
MAX_COPIES: Final = 100

ErasedSidesOption = Annotated[
    int, typer.Option("--sides", parser=side_count, help="1 or 2 sides to erase")
]


def _print_erase(report: WriteReport) -> None:
    for line in report.lines:
        typer.echo(line)
    typer.echo(ERASED if report.verified else LEFT_BEHIND)


def erase(
    *,
    sides: ErasedSidesOption = 1,
    backup: BackupOption = None,
    yes: YesOption = False,
    retries: RetriesOption = 3,
) -> None:
    plan = WritePlan(ask=prompter(yes=yes), backup=backup, retries=retries, long_side=False)
    with closing(open_drive()) as drive:
        report = write_disk(drive, erased_disk(sides=sides), plan)
        _print_erase(report)
        raise typer.Exit(code=0 if report.verified else 1)


DuplicatedArgument = Annotated[Path, typer.Argument(help="the image to copy onto each disk")]
CountOption = Annotated[
    int, typer.Option("--count", min=1, max=MAX_COPIES, help="how many disks to write")
]


def duplicate_command(
    image: DuplicatedArgument,
    *,
    count: CountOption = 1,
    yes: YesOption = False,
    retries: RetriesOption = 3,
) -> None:
    disk = decode_image(image)[0]
    try:
        refuse_long_sides(disk)
    except LongSideError as error:
        raise fail(str(error)) from error
    with closing(open_drive()) as drive:
        report = duplicate(
            drive, drive, disk, count=count, ask=prompter(yes=yes), retries=retries, progress=step
        )
    for line in duplicate_lines(report):
        typer.echo(line)
    raise typer.Exit(code=0 if report.verified == count else 1)


def register(app: typer.Typer) -> None:
    app.command(
        rich_help_panel=Family.HARDWARE,
        help="Erase a disk to the factory fill, after a backup, and confirm no block remains.",
    )(erase)
    app.command(
        name="duplicate",
        rich_help_panel=Family.HARDWARE,
        help="Write one image onto a queue of disks, reading each copy back.",
    )(duplicate_command)
