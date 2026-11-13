from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.build.blank import DEFAULT_GAME_NAME, blank_image
from fdstoolkit.build.calibration import DECIDES_ITSELF, calibration_image
from fdstoolkit.cli.common import (
    Container,
    Family,
    container_of,
    decode_image,
    fail,
    guard_output,
    is_save_file,
    side_count,
)
from fdstoolkit.codecs import fds, qd
from fdstoolkit.core.diagnostics import Severity, worst_severity


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
    disk, _, _, _ = decode_image(image)
    target = container_of(output)
    guard_output(output, force=force)
    if header and is_save_file(output):
        message = "an .srm save is headerless, so --header cannot apply to it"
        raise fail(message)

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
    sides: Annotated[int, typer.Option("--sides", parser=side_count, help="1 or 2 sides")] = 1,
    formatted: Annotated[bool, typer.Option("--formatted", help="write a disk info block")] = False,
    header: Annotated[bool, typer.Option("--header", help="write an fwNES header")] = False,
    game_name: Annotated[str, typer.Option("--game-name", help="three-character code")] = "   ",
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
    calibration: Annotated[
        bool,
        typer.Option("--calibration", help="the calibration disk: two sides of known pulses"),
    ] = False,
) -> None:
    guard_output(output, force=force)
    if calibration:
        _calibration_image(output, header=header, plain=(sides, formatted, game_name))
        return
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


def _calibration_image(output: Path, *, header: bool, plain: tuple[int, bool, str]) -> None:
    if plain != (1, False, DEFAULT_GAME_NAME):
        raise fail(DECIDES_ITSELF)
    data = calibration_image(headered=header)
    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes)")
    typer.echo(
        "write it only on a drive you trust, with write --calibration --trusted-drive, "
        "which lists every adjustment that drive needs first"
    )


def register(app: typer.Typer) -> None:
    app.command(rich_help_panel=Family.CONTAINER, help="Convert between .fds and .qd.")(convert)
    app.command(
        rich_help_panel=Family.CONTAINER, help="Create a blank image, or the calibration disk."
    )(blank)
