from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import fail
from fdstoolkit.drive.classes import Reading, measure_classes
from fdstoolkit.drive.speed import Verdict, from_cycles
from fdstoolkit.report import as_json


def classes(
    capture: Annotated[Path, typer.Argument(help="a raw03 capture kept by dump --raw")],
    *,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Judge how evenly the drive separates the three pulse lengths."""
    if not capture.is_file():
        message = f"file not found: {capture}"
        raise fail(message)

    try:
        report = measure_classes(capture.read_bytes())
    except ValueError as error:
        raise fail(str(error)) from error

    if json_output:
        typer.echo(
            as_json(
                {
                    "reading": report.reading.value,
                    "pulses": report.total,
                    "shares": [round(share, 5) for share in report.shares],
                    "glitches": report.glitches,
                    "glitch_rate": round(report.glitch_rate, 6),
                    "drift": round(report.drift, 5),
                }
            )
        )
        raise typer.Exit(code=0 if report.reading is Reading.HEALTHY else 1)

    typer.echo(report.render())
    raise typer.Exit(code=0 if report.reading is Reading.HEALTHY else 1)


def reading(
    cycles: Annotated[
        float,
        typer.Argument(help="average CPU cycles between bytes, as the console tool shows it"),
    ],
    *,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Read a console tool's cycles-between-bytes figure and say which way to adjust."""
    try:
        report = from_cycles(cycles)
    except ValueError as error:
        raise fail(str(error)) from error

    if json_output:
        typer.echo(
            as_json(
                {
                    "cycles_per_byte": cycles,
                    "bit_rate_hz": round(report.bit_rate_hz, 1),
                    "error": round(report.error, 5),
                    "verdict": report.verdict.value,
                    "direction": report.direction.value,
                    "advice": report.advice,
                }
            )
        )
        raise typer.Exit(code=0 if report.verdict is Verdict.FINE else 1)

    typer.echo(report.render())
    raise typer.Exit(code=0 if report.verdict is Verdict.FINE else 1)


def register(app: typer.Typer) -> None:
    app.command()(classes)
    app.command()(reading)
