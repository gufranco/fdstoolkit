from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import Family, decode_image, fail
from fdstoolkit.quality.confidence import score_disk
from fdstoolkit.quality.grade import grade_disk
from fdstoolkit.quality.reads import compare_reads
from fdstoolkit.report import as_json


def reads(
    images: Annotated[list[Path], typer.Argument(help="two or more dumps of one disk")],
    *,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Compare repeated dumps of one disk and report which blocks move."""
    disks = [decode_image(path)[0] for path in images]

    try:
        stats = compare_reads(disks)
    except ValueError as error:
        raise fail(str(error)) from error

    if json_output:
        typer.echo(
            as_json(
                {
                    "passes": stats.passes,
                    "stability": round(stats.stability, 6),
                    "decay": stats.decay.value,
                    "ones_lost": stats.ones_lost,
                    "ones_gained": stats.ones_gained,
                    "unstable": [list(item) for item in stats.unstable_blocks],
                }
            )
        )
        raise typer.Exit(code=0 if not stats.unstable_blocks else 1)

    typer.echo(f"passes        {stats.passes}")
    typer.echo(f"stability     {stats.stability:.2%}")
    typer.echo(f"decay         {stats.decay.value}")
    typer.echo(f"bits lost     {stats.ones_lost}")
    typer.echo(f"bits gained   {stats.ones_gained}")
    for item in stats.blocks:
        if item.stable:
            continue
        typer.echo(
            f"side {item.side} block {item.block:3d}  {item.kind:<11} "
            f"{item.variants} variants, {item.flip_rate:.1%} flip rate, "
            f"{item.bits_differing} bits"
        )
    raise typer.Exit(code=0 if not stats.unstable_blocks else 1)


def grade(
    image: Annotated[Path, typer.Argument(help="the image to grade")],
    read: Annotated[
        list[Path] | None,
        typer.Option("--read", help="another dump of the same disk, repeatable"),
    ] = None,
    *,
    block_map: Annotated[
        bool, typer.Option("--map", help="print the per-block confidence")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Grade an image and state the measurement behind the grade."""
    disk, findings, _, _ = decode_image(image)

    stats = None
    if read:
        disks = [disk, *[decode_image(path)[0] for path in read]]
        try:
            stats = compare_reads(disks)
        except ValueError as error:
            raise fail(str(error)) from error

    confidence = score_disk(disk, reads=stats)

    report = grade_disk(confidence=confidence, findings=findings, reads=stats)

    if json_output:
        typer.echo(
            as_json(
                {
                    "grade": report.grade.value,
                    "confidence": round(report.confidence, 6),
                    "reasons": [
                        {
                            "metric": reason.metric,
                            "value": reason.value,
                            "threshold": reason.threshold,
                            "passed": reason.passed,
                        }
                        for reason in report.reasons
                    ],
                }
            )
        )
        raise typer.Exit(code=0 if report.grade.value == "clean" else 1)

    typer.echo(report.render())
    for reason in report.reasons:
        mark = "ok " if reason.passed else "bad"
        typer.echo(f"  {mark}  {reason.render()}")
    if block_map:
        for item in confidence.blocks:
            typer.echo(
                f"side {item.side} block {item.block:3d}  {item.kind:<11} "
                f"{item.confidence:6.1%}  {', '.join(item.basis)}"
            )
    raise typer.Exit(code=0 if report.grade.value == "clean" else 1)


def register(app: typer.Typer) -> None:
    app.command(rich_help_panel=Family.CHECK)(reads)
    app.command(rich_help_panel=Family.CHECK)(grade)
