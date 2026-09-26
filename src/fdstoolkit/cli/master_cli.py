from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from fdstoolkit.cli.common import (
    Family,
    container_of,
    decode_image,
    encode_image,
    fail,
    guard_output,
    load_captures,
)
from fdstoolkit.core.disk import Disk
from fdstoolkit.drive.recovery import Rebuild, rebuild
from fdstoolkit.master.splice import splice
from fdstoolkit.quality.consensus import build_consensus
from fdstoolkit.report import as_json


def splice_command(
    image: Annotated[Path, typer.Argument(help="the image to repair")],
    donor: Annotated[
        list[Path], typer.Option("--donor", help="another dump of the same disk, repeatable")
    ],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the result")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Repair a bad block by taking it from another dump of the same disk."""
    container = container_of(output)
    guard_output(output, force=force)
    primary, _, _, _ = decode_image(image)
    donors = [decode_image(path)[0] for path in donor]

    try:
        result = splice(primary, donors)
    except ValueError as error:
        raise fail(str(error)) from error

    data = encode_image(result.disk, container)
    output.write_bytes(data)

    for item in result.splices:
        typer.echo(
            f"side {item.side} block {item.block:3d}  {item.kind:<11} "
            f"taken from {donor[item.donor].name}"
        )
    for side_index, block_index in result.unrepaired:
        typer.echo(f"side {side_index} block {block_index}: no donor carries a good copy")
    typer.echo(f"wrote {output} ({len(data)} bytes)")
    raise typer.Exit(code=0 if result.complete else 1)


def consensus(
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the merged disk")],
    paths: Annotated[
        list[Path] | None, typer.Argument(help="dumps of one disk, two or more without captures")
    ] = None,
    *,
    captures: Annotated[
        Path | None,
        typer.Option("--captures", help="the captures a dump --raw kept, a folder or a zip"),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
    stability_map: Annotated[
        bool, typer.Option("--map", help="print the per-block agreement")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Merge dumps of one disk block by block, by majority, and name every disagreement."""
    dumps = paths or []
    if not dumps and captures is None:
        message = "a consensus needs dumps, saved captures, or both"
        raise fail(message)
    missing = [path for path in dumps if not path.is_file()]
    if missing:
        message = f"not found: {', '.join(str(path) for path in missing)}"
        raise fail(message)
    container_of(output)
    guard_output(output, force=force)
    rebuilt = None if captures is None else rebuild(load_captures(captures))
    disks = [decode_image(path)[0] for path in dumps]
    if rebuilt is not None and not disks:
        _write_rebuilt(rebuilt, output, json_output=json_output)
    if rebuilt is not None:
        for line in rebuilt.lines:
            typer.echo(line, err=json_output)
        disks.append(rebuilt.disk)
    _disk_consensus(disks, output, stability_map=stability_map, json_output=json_output)


def _write_rebuilt(rebuilt: Rebuild, output: Path, *, json_output: bool) -> NoReturn:
    data = encode_image(rebuilt.disk, container_of(output))
    output.write_bytes(data)
    code = 0 if not rebuilt.unresolved else 1
    if json_output:
        typer.echo(
            as_json(
                {
                    "output": str(output),
                    "bytes": len(data),
                    "unresolved": [list(item) for item in rebuilt.unresolved],
                }
            )
        )
        raise typer.Exit(code=code)
    for line in rebuilt.lines:
        typer.echo(line)
    typer.echo(f"wrote {output} ({len(data)} bytes)")
    raise typer.Exit(code=code)


def _disk_consensus(
    disks: list[Disk], output: Path, *, stability_map: bool, json_output: bool
) -> NoReturn:
    try:
        result = build_consensus(disks)
    except ValueError as error:
        raise fail(str(error)) from error

    data = encode_image(result.disk, container_of(output))
    output.write_bytes(data)
    code = 0 if not result.disagreements else 1

    if json_output:
        typer.echo(
            as_json(
                {
                    "output": str(output),
                    "bytes": len(data),
                    "disagreements": [list(item) for item in result.disagreements],
                    "missing": [list(item) for item in result.missing],
                }
            )
        )
        raise typer.Exit(code=code)

    if stability_map:
        for entry in result.stability:
            typer.echo(
                f"side {entry.side} block {entry.block:3d}  {entry.kind:<11} "
                f"{entry.agreement:6.1%}  {entry.variants} variant(s)  {entry.verdict}"
            )
    for side_index, block_index in result.disagreements:
        typer.echo(f"side {side_index} block {block_index}: the dumps disagree")
    for side_index, block_index, absent in result.missing:
        typer.echo(
            f"side {side_index} block {block_index}: missing from {absent} dump(s), "
            "decided by the others"
        )
    typer.echo(f"wrote {output} ({len(data)} bytes)")
    raise typer.Exit(code=code)


def register(app: typer.Typer) -> None:
    app.command(name="splice", rich_help_panel=Family.REPAIR)(splice_command)
    app.command(rich_help_panel=Family.REPAIR)(consensus)
