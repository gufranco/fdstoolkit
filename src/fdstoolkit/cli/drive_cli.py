from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import Family, fail
from fdstoolkit.drive.classes import ClassReport, Reading, measure_classes
from fdstoolkit.drive.speed import SpeedReport, Verdict, from_cycles
from fdstoolkit.report import as_json


def _speed(cycles: float) -> SpeedReport:
    try:
        return from_cycles(cycles)
    except ValueError as error:
        raise fail(str(error)) from error


def _classes(capture: Path) -> ClassReport:
    if not capture.is_file():
        message = f"file not found: {capture}"
        raise fail(message)
    try:
        return measure_classes(capture.read_bytes())
    except ValueError as error:
        raise fail(str(error)) from error


def _speed_json(cycles: float) -> dict[str, object]:
    report = _speed(cycles)
    return {
        "cycles_per_byte": cycles,
        "bit_rate_hz": round(report.bit_rate_hz, 1),
        "error": round(report.error, 5),
        "verdict": report.verdict.value,
        "direction": report.direction.value,
        "advice": report.advice,
    }


def _classes_json(report: ClassReport) -> dict[str, object]:
    return {
        "reading": report.reading.value,
        "pulses": report.total,
        "shares": [round(share, 5) for share in report.shares],
        "glitches": report.glitches,
        "glitch_rate": round(report.glitch_rate, 6),
        "drift": round(report.drift, 5),
    }


LABEL_WIDTH = 9


def _labelled(label: str, text: str) -> str:
    return f"{label:<{LABEL_WIDTH}}" + text.replace("\n", "\n" + " " * LABEL_WIDTH)


def calibrate(
    cycles: Annotated[
        float | None,
        typer.Option(
            "--cycles", help="average CPU cycles between bytes, as a console disk-lister shows it"
        ),
    ] = None,
    capture: Annotated[
        Path | None,
        typer.Option("--capture", help="a raw03 capture kept by dump --raw"),
    ] = None,
    *,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Check the drive: its speed from a console reading, its pulse separation from a capture."""
    if cycles is None and capture is None:
        message = "calibrating needs --cycles, --capture, or both"
        raise fail(message)

    speed = None if cycles is None else _speed(cycles)
    classes = None if capture is None else _classes(capture)
    ok = (speed is None or speed.verdict is Verdict.FINE) and (
        classes is None or classes.reading is Reading.HEALTHY
    )

    if json_output:
        typer.echo(
            as_json(
                {
                    "speed": None if cycles is None else _speed_json(cycles),
                    "classes": None if classes is None else _classes_json(classes),
                }
            )
        )
        raise typer.Exit(code=0 if ok else 1)

    if speed is not None:
        typer.echo(_labelled("speed", speed.render()))
    if classes is not None:
        typer.echo(_labelled("classes", classes.render()))
    raise typer.Exit(code=0 if ok else 1)


def register(app: typer.Typer) -> None:
    app.command(rich_help_panel=Family.HARDWARE)(calibrate)
