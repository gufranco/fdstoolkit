from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.common import (
    Container,
    container_of,
    decode_image,
    fail,
    guard_output,
)
from fdstoolkit.codecs import fds, qd
from fdstoolkit.core.canon import canonicalise, digest_string, profile_by_name
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


def canon(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    *,
    profile: Annotated[str, typer.Option("--profile", help="raw, content or data")] = "content",
    output: Annotated[
        Path | None,
        typer.Option("-o", "--output", help="write the canonical image"),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Print the canonical digest, and optionally write the canonical image."""
    disk, _, _, _ = decode_image(image)
    try:
        result = canonicalise(disk, profile_by_name(profile))
    except ValueError as error:
        raise fail(str(error)) from error

    typer.echo(digest_string(result))
    if output is None:
        return
    guard_output(output, force=force)
    output.write_bytes(result.data)
    typer.echo(f"wrote {output} ({len(result.data)} bytes)")


def blank(
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write")],
    *,
    sides: Annotated[int, typer.Option("--sides", min=1, max=8, help="side count")] = 1,
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


def register(app: typer.Typer) -> None:
    app.command()(convert)
    app.command()(canon)
    app.command()(blank)
