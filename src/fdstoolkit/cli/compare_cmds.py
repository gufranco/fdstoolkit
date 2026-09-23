from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import (
    decode_image,
    fail,
)
from fdstoolkit.edit.saves import find_save_candidates
from fdstoolkit.quality.consensus import compare_images
from fdstoolkit.quality.explain import Explanation, explain
from fdstoolkit.report import as_json


def diff_command(
    first: Annotated[Path, typer.Argument(help="the first image")],
    second: Annotated[Path, typer.Argument(help="the second image")],
    *,
    explain_fields: Annotated[
        bool, typer.Option("--explain", help="name the fields and files that differ")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Compare two images block by block."""
    left, _, _, _ = decode_image(first)
    right, _, _, _ = decode_image(second)
    report = compare_images(left, right)

    if explain_fields:
        _print_explanation(first, second, explain(left, right), json_output=json_output)
        raise typer.Exit(code=0 if report.identical else 1)

    if json_output:
        typer.echo(
            as_json(
                {
                    "first": str(first),
                    "second": str(second),
                    "identical": report.identical,
                    "summary": report.summary,
                    "differing_blocks": [list(pair) for pair in report.differing_blocks],
                }
            )
        )
    else:
        typer.echo(report.summary)
        for side_index, block_index in report.differing_blocks:
            typer.echo(f"  side {side_index} block {block_index}")

    raise typer.Exit(code=0 if report.identical else 1)


def _print_explanation(
    first: Path, second: Path, result: Explanation, *, json_output: bool
) -> None:
    if json_output:
        typer.echo(
            as_json(
                {
                    "first": str(first),
                    "second": str(second),
                    "identical": result.identical,
                    "same_software": result.same_software,
                    "headline": result.headline,
                    "fields": [
                        {
                            "side": entry.side,
                            "field": entry.field,
                            "description": entry.description,
                            "identity": entry.identity,
                            "first": entry.left,
                            "second": entry.right,
                        }
                        for entry in result.fields
                    ],
                    "files": [
                        {
                            "side": entry.side,
                            "position": entry.position,
                            "name": entry.name,
                            "change": str(entry.change),
                            "detail": entry.detail,
                        }
                        for entry in result.files
                    ],
                }
            )
        )
        return

    typer.echo(result.headline)
    for entry in result.fields:
        marker = "identity" if entry.identity else "provenance"
        typer.echo(
            f"  side {entry.side} {entry.field} ({marker}): {entry.left} against {entry.right}"
        )
    for entry in result.files:
        typer.echo(
            f"  side {entry.side} file {entry.position} {entry.name}: "
            f"{entry.change}, {entry.detail}"
        )


def saves(
    images: Annotated[list[Path], typer.Argument(help="two or more dumps of the same release")],
    *,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Compare dumps of one release and report which file looks like the save."""
    disks = [decode_image(path)[0] for path in images]
    try:
        candidates = find_save_candidates(disks)
    except ValueError as error:
        raise fail(str(error)) from error

    if json_output:
        typer.echo(
            as_json(
                {
                    "images": [str(path) for path in images],
                    "candidates": [
                        {
                            "side": candidate.side,
                            "position": candidate.position,
                            "name": candidate.name,
                            "size": candidate.size,
                            "differing_bytes": candidate.differing_bytes,
                            "name_matches_pattern": candidate.name_matches_pattern,
                        }
                        for candidate in candidates
                    ],
                }
            )
        )
        return

    if not candidates:
        typer.echo("no save candidate: every file agrees across the dumps")
        return
    for candidate in candidates:
        marker = ", name reads like a save" if candidate.name_matches_pattern else ""
        typer.echo(
            f"side {candidate.side} file {candidate.position} {candidate.name}: "
            f"{candidate.differing_bytes} of {candidate.size} bytes differ{marker}"
        )


def register(app: typer.Typer) -> None:
    app.command(name="diff")(diff_command)
    app.command()(saves)
