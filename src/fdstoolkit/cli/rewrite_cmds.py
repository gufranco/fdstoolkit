from __future__ import annotations

from contextlib import closing
from typing import Annotated, Final

import typer

from fdstoolkit.cli.common import Family, RetriesOption, YesOption, side_count
from fdstoolkit.cli.hardware_cmds import (
    BackupOption,
    WritePlan,
    open_drive,
    prompter,
    write_disk,
)
from fdstoolkit.hardware.writing import WriteReport
from fdstoolkit.quality.surface_disks import erased_disk

ERASED: Final = "every side reads back with no block"
LEFT_BEHIND: Final = "the erase left blocks behind, listed above"

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


def register(app: typer.Typer) -> None:
    app.command(
        rich_help_panel=Family.HARDWARE,
        help="Erase a disk to the factory fill, after a backup, and confirm no block remains.",
    )(erase)
