from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Annotated, Final

import typer

from fdstoolkit.cli.common import (
    Family,
    ForceOption,
    RetriesOption,
    YesOption,
    container_of,
    decode_image,
    encode_image,
    fail,
    guard_output,
    side_count,
    writer_for,
)
from fdstoolkit.cli.hardware_cmds import (
    BackupOption,
    WritePlan,
    open_drive,
    print_write,
    prompter,
    step,
    write_disk,
)
from fdstoolkit.core.disk import Disk
from fdstoolkit.hardware.duplicate import duplicate, duplicate_lines
from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.hardware.refresh import RefreshPlan, refresh_disk
from fdstoolkit.hardware.session import MAX_PASSES, LongSideError, SideFlipError, WriteRefusedError
from fdstoolkit.hardware.writing import WriteReport, refuse_long_sides
from fdstoolkit.quality.surface_disks import erased_disk

ERASED: Final = "every side reads back with no block"
LEFT_BEHIND: Final = "the erase left blocks behind, listed above"
MAX_COPIES: Final = 100

ErasedSidesOption = Annotated[
    int, typer.Option("--sides", parser=side_count, help="1 or 2 sides to erase")
]


def _print_erase(report: WriteReport, track_packets: int | None) -> None:
    for line in report.lines:
        typer.echo(line)
    if track_packets is not None:
        typer.echo(f"the track ended after {track_packets} packets")
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
        _print_erase(report, drive.track_packets)
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


RefreshOutputOption = Annotated[
    Path, typer.Option("-o", "--output", help="where to keep the rebuilt image before writing it")
]
RefreshPassesOption = Annotated[
    int, typer.Option("--passes", min=1, max=MAX_PASSES, help="read each side this often first")
]


def _keeper(output: Path) -> Callable[[Disk], None]:
    container = container_of(output)

    def keep(image: Disk) -> None:
        output.write_bytes(encode_image(image, container))
        typer.echo(f"kept the rebuilt image in {output}")

    return keep


def refresh(
    *,
    output: RefreshOutputOption,
    sides: ErasedSidesOption = 1,
    passes: RefreshPassesOption = 3,
    retries: RetriesOption = 3,
    backup: BackupOption = None,
    yes: YesOption = False,
    force: ForceOption = False,
) -> None:
    guard_output(output, force=force)
    ask = prompter(yes=yes)
    backed = None if backup is None else writer_for(backup)
    plan = RefreshPlan(sides, passes, retries, ask, _keeper(output), backed, ask, step)
    with closing(open_drive()) as drive:
        try:
            report = refresh_disk(drive, plan)
        except (HardwareFaultError, WriteRefusedError, SideFlipError) as error:
            raise fail(str(error)) from error
    for line in report.lines:
        typer.echo(line)
    print_write(report.write)
    raise typer.Exit(code=0 if report.write.verified else 1)


def register(app: typer.Typer) -> None:
    app.command(
        rich_help_panel=Family.HARDWARE,
        help="Erase a disk to the factory fill, after a backup, and confirm no block remains.",
    )(erase)
    app.command(
        rich_help_panel=Family.HARDWARE,
        help="Read a weak disk, settle every block, and write it back as the factory laid it out.",
    )(refresh)
    app.command(
        name="duplicate",
        rich_help_panel=Family.HARDWARE,
        help="Write one image onto a queue of disks, reading each copy back.",
    )(duplicate_command)
