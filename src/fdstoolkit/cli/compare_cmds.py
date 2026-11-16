from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import Family, JsonOption, decode_image
from fdstoolkit.quality.consensus import ComparisonReport, compare_images
from fdstoolkit.quality.explain import Explanation, explain
from fdstoolkit.report import as_json

FirstArgument = Annotated[Path, typer.Argument(help="the first image")]
SecondArgument = Annotated[Path, typer.Argument(help="the second image")]
ExplainOption = Annotated[
    bool, typer.Option("--explain", help="name the fields and files that differ")
]


def _print_report(
    first: Path, second: Path, report: ComparisonReport, *, json_output: bool
) -> None:
    if json_output:
        payload = {
            "first": str(first),
            "second": str(second),
            "identical": report.identical,
            "summary": report.summary,
            "differing_blocks": [list(pair) for pair in report.differing_blocks],
        }
        typer.echo(as_json(payload))
        return
    typer.echo(report.summary)
    for side_index, block_index in report.differing_blocks:
        typer.echo(f"  side {side_index} block {block_index}")


def diff_command(
    first: FirstArgument,
    second: SecondArgument,
    *,
    explain_fields: ExplainOption = False,
    json_output: JsonOption = False,
) -> None:
    left, _, _, _ = decode_image(first)
    right, _, _, _ = decode_image(second)
    report = compare_images(left, right)
    if explain_fields:
        _print_explanation(first, second, explain(left, right), json_output=json_output)
    else:
        _print_report(first, second, report, json_output=json_output)
    raise typer.Exit(code=0 if report.identical else 1)


def _field_rows(result: Explanation) -> list[dict[str, object]]:
    return [
        {
            "side": entry.side,
            "field": entry.field,
            "description": entry.description,
            "identity": entry.identity,
            "first": entry.left,
            "second": entry.right,
        }
        for entry in result.fields
    ]


def _file_rows(result: Explanation) -> list[dict[str, object]]:
    return [
        {
            "side": entry.side,
            "position": entry.position,
            "name": entry.name,
            "change": str(entry.change),
            "detail": entry.detail,
        }
        for entry in result.files
    ]


def _explanation_payload(first: Path, second: Path, result: Explanation) -> dict[str, object]:
    return {
        "first": str(first),
        "second": str(second),
        "identical": result.identical,
        "same_software": result.same_software,
        "headline": result.headline,
        "fields": _field_rows(result),
        "files": _file_rows(result),
    }


def _print_explanation(
    first: Path, second: Path, result: Explanation, *, json_output: bool
) -> None:
    if json_output:
        typer.echo(as_json(_explanation_payload(first, second, result)))
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


def register(app: typer.Typer) -> None:
    app.command(
        name="diff", rich_help_panel=Family.CHECK, help="Compare two images block by block."
    )(diff_command)
