from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import (
    Family,
    ForceOption,
    RetriesOption,
    YesOption,
    fail,
    guard_output,
    writer_for,
)
from fdstoolkit.cli.hardware_cmds import BackupOption, open_drive, prompter, step
from fdstoolkit.core.disk import SIDES_PER_DISK
from fdstoolkit.edit.disk_saves import SaveBackup, SaveBackupError, backup_bytes, load_backup
from fdstoolkit.hardware.disk_save import back_up_save, restore_save
from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.hardware.session import WriteRefusedError
from fdstoolkit.hardware.writing import CHANGED_BLOCK, STALE_BLOCK, SideWrite

STOPS = (HardwareFaultError, WriteRefusedError, SaveBackupError)

SaveOutputOption = Annotated[Path, typer.Option("-o", "--output", help="where to keep the save")]
SaveSideOption = Annotated[
    int,
    typer.Option(
        "--side", min=0, max=SIDES_PER_DISK - 1, help="the side face down, its label facing up"
    ),
]
FileOption = Annotated[
    int | None,
    typer.Option("--file", min=0, help="the save file's number, when its name does not say so"),
]
SavedArgument = Annotated[Path, typer.Argument(help="a save kept by save-backup")]


def save_backup(
    *,
    output: SaveOutputOption,
    side: SaveSideOption = 0,
    file: FileOption = None,
    retries: RetriesOption = 3,
    force: ForceOption = False,
) -> None:
    guard_output(output, force=force)
    with closing(open_drive()) as drive:
        try:
            backup = back_up_save(drive, side=side, number=file, retries=retries, progress=step)
        except STOPS as error:
            raise fail(str(error)) from error
    output.write_bytes(backup_bytes(backup))
    typer.echo(
        f"kept file {backup.number} {backup.name}, {len(backup.data)} bytes, of "
        f"{backup.identity.render()} side {backup.side} in {output}"
    )


def _loaded(path: Path) -> SaveBackup:
    try:
        return load_backup(path.read_bytes())
    except SaveBackupError as error:
        raise fail(str(error)) from error


def _print_restore(backup: SaveBackup, written: SideWrite) -> None:
    for block in written.mismatched:
        text = STALE_BLOCK if block in written.stale else CHANGED_BLOCK
        typer.echo(f"side {backup.side}: block {block} {text}")
    state = "did not read back as written" if written.mismatched else "read back as written"
    typer.echo(f"restored file {backup.number} {backup.name} on side {backup.side}, {state}")


def _discard(data: bytes) -> None:
    del data


def save_restore(
    saved: SavedArgument,
    *,
    backup: BackupOption = None,
    yes: YesOption = False,
    retries: RetriesOption = 3,
) -> None:
    kept = _loaded(saved)
    keep = writer_for(backup) if backup is not None else _discard
    with closing(open_drive()) as drive:
        try:
            written = restore_save(
                drive, kept, retries=retries, confirm=prompter(yes=yes), keep=keep, progress=step
            )
        except STOPS as error:
            raise fail(str(error)) from error
    _print_restore(kept, written)
    raise typer.Exit(code=1 if written.mismatched else 0)


def register(app: typer.Typer) -> None:
    app.command(
        name="save-backup",
        rich_help_panel=Family.HARDWARE,
        help="Keep the save file of the disk in the drive, with the game it belongs to.",
    )(save_backup)
    app.command(
        name="save-restore",
        rich_help_panel=Family.HARDWARE,
        help="Put a kept save back on the disk it came from, rewriting only that file.",
    )(save_restore)
