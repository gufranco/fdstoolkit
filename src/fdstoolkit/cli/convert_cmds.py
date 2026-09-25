from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.targets import TARGETS, export_for, swap_warnings
from fdstoolkit.cli.common import (
    Container,
    Family,
    TargetChoice,
    container_of,
    decode_image,
    fail,
    guard_output,
)
from fdstoolkit.codecs import fds, qd
from fdstoolkit.core.diagnostics import Severity, worst_severity
from fdstoolkit.core.disk import SIDES_PER_DISK


def convert(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write")],
    *,
    header: Annotated[
        bool,
        typer.Option("--header/--no-header", help="write an fwNES header"),
    ] = False,
    crc_mode: Annotated[
        qd.CrcMode,
        typer.Option("--crc-mode", help="CRC handling when writing a .qd"),
    ] = qd.CrcMode.PRESERVE,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Convert between .fds and .qd."""
    disk, _, _, _ = decode_image(image)
    target = container_of(output)
    guard_output(output, force=force)

    if target is Container.FDS:
        data, findings = fds.encode(disk, headered=header)
    else:
        data, findings = qd.encode(disk, crc_mode=crc_mode)

    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes)")
    for finding in findings:
        typer.echo(f"  {finding.render()}")
    if worst_severity(findings) is Severity.ERROR:
        raise typer.Exit(code=1)


def blank(
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write")],
    *,
    sides: Annotated[
        int, typer.Option("--sides", min=1, max=SIDES_PER_DISK, help="1 or 2 sides")
    ] = 1,
    formatted: Annotated[bool, typer.Option("--formatted", help="write a disk info block")] = False,
    header: Annotated[bool, typer.Option("--header", help="write an fwNES header")] = False,
    game_name: Annotated[str, typer.Option("--game-name", help="three-character code")] = "   ",
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Create a blank image."""
    guard_output(output, force=force)
    try:
        data = blank_image(
            sides=sides,
            headered=header,
            formatted=formatted,
            game_name=game_name,
        )
    except ValueError as error:
        raise fail(str(error)) from error
    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes)")


def export(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    target: Annotated[TargetChoice, typer.Option("--target", help="the device or emulator")],
    directory: Annotated[Path, typer.Option("-d", "--directory", help="the card or folder root")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite existing files")] = False,
) -> None:
    """Write an image in the layout a device or emulator expects."""
    disk, _, _, _ = decode_image(image)

    try:
        written = export_for(
            disk,
            target=target.value,
            directory=directory,
            stem=image.stem,
            force=force,
        )
    except FileExistsError as error:
        message = f"{error}, pass --force to overwrite"
        raise fail(message) from error

    typer.echo(TARGETS[target.value].description)
    for path in written:
        typer.echo(f"wrote {path}")
    for warning in swap_warnings(image.stem, target=target.value):
        typer.echo(f"  {warning}")


def register(app: typer.Typer) -> None:
    app.command(rich_help_panel=Family.CONTAINER)(convert)
    app.command(rich_help_panel=Family.CONTAINER)(blank)
    app.command(rich_help_panel=Family.CONTAINER)(export)
