from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from fdstoolkit.cli.common import Family, decode_image, fail, guard_output
from fdstoolkit.codecs import fds
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
    guard_output(output, force=force)
    primary, _, _, _ = decode_image(image)
    donors = [decode_image(path)[0] for path in donor]

    try:
        result = splice(primary, donors)
    except ValueError as error:
        raise fail(str(error)) from error

    data, _ = fds.encode(result.disk, headered=False)
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
    paths: Annotated[list[Path], typer.Argument(help="two or more dumps of one disk")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the merged disk")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
    stability_map: Annotated[
        bool, typer.Option("--map", help="print the per-block agreement")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Merge dumps of one disk block by block, by majority, and name every disagreement."""
    missing = [path for path in paths if not path.is_file()]
    if missing:
        message = f"not found: {', '.join(str(path) for path in missing)}"
        raise fail(message)
    _disk_consensus(
        paths, output, force=force, stability_map=stability_map, json_output=json_output
    )


def _disk_consensus(
    paths: list[Path], output: Path, *, force: bool, stability_map: bool, json_output: bool
) -> NoReturn:
    guard_output(output, force=force)
    try:
        result = build_consensus([decode_image(path)[0] for path in paths])
    except ValueError as error:
        raise fail(str(error)) from error

    data, _ = fds.encode(result.disk, headered=False)
    output.write_bytes(data)
    code = 0 if not result.disagreements else 1

    if json_output:
        typer.echo(
            as_json(
                {
                    "output": str(output),
                    "bytes": len(data),
                    "disagreements": [list(item) for item in result.disagreements],
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
    typer.echo(f"wrote {output} ({len(data)} bytes)")
    raise typer.Exit(code=code)


def register(app: typer.Typer) -> None:
    app.command(name="splice", rich_help_panel=Family.REPAIR)(splice_command)
    app.command(rich_help_panel=Family.REPAIR)(consensus)
