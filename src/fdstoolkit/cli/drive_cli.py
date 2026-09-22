from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import fail
from fdstoolkit.drive.advise import advise
from fdstoolkit.drive.bracket import Setting, bracket_of
from fdstoolkit.drive.spec import accept_band
from fdstoolkit.flux.analysis import analyse_intervals
from fdstoolkit.flux.load import CaptureFormat, load_capture
from fdstoolkit.flux.model import FluxCapture
from fdstoolkit.report import as_json


def _capture(path: Path, fmt: CaptureFormat | None) -> FluxCapture:
    if not path.is_file():
        message = f"file not found: {path}"
        raise fail(message)
    try:
        return load_capture(path.read_bytes(), fmt=fmt)
    except ValueError as error:
        raise fail(str(error)) from error


def _intervals(path: Path, fmt: CaptureFormat | None) -> tuple[int, ...]:
    capture = _capture(path, fmt)
    if capture.quantised:
        message = (
            f"{path.name} carries pulse classes, not pulse timing. "
            "The device already rounded every pulse to one of three nominal lengths, "
            "so a speed measured from it would describe the rounding rather than the drive. "
            "Capture interval counts instead."
        )
        raise fail(message)
    return tuple(value for track in capture.tracks for value in track.intervals(0))


def tune(
    capture: Annotated[Path, typer.Argument(help="a pulse capture from the drive")],
    fmt: Annotated[
        CaptureFormat | None,
        typer.Option("--format", help="override the detected capture format"),
    ] = None,
    *,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Measure the drive and say what to adjust, coarse first, then fine."""
    result = advise(_intervals(capture, fmt))

    if json_output:
        typer.echo(
            as_json(
                {
                    "settled": result.settled,
                    "score": round(result.score, 4),
                    "speed": {
                        "bit_rate_hz": round(result.speed.bit_rate_hz, 1),
                        "cell_ns": round(result.speed.cell_ns, 1),
                        "counts": round(result.speed.counts, 2),
                        "cycles_per_byte": round(result.speed.cycles_per_byte, 2),
                        "error": round(result.speed.error, 5),
                        "verdict": result.speed.verdict.value,
                        "direction": result.speed.direction.value,
                        "headroom": round(result.speed.headroom, 4),
                    },
                    "stability": {
                        "motion": result.stability.motion.value,
                        "wow_flutter": round(result.stability.wow_flutter, 5),
                        "drift": round(result.stability.drift, 5),
                        "spread": round(result.stability.spread, 5),
                        "quality": round(result.stability.quality, 4),
                    },
                    "actions": [
                        {
                            "stage": action.stage.value,
                            "subject": action.subject,
                            "finding": action.finding,
                            "action": action.action,
                            "gain": round(action.gain, 4),
                        }
                        for action in result.actions
                    ],
                }
            )
        )
        raise typer.Exit(code=0 if result.settled else 1)

    typer.echo(result.render())
    raise typer.Exit(code=0 if result.settled else 1)


def tune_sweep(
    captures: Annotated[
        list[Path], typer.Argument(help="one capture per trimmer setting, any order")
    ],
    fmt: Annotated[
        CaptureFormat | None,
        typer.Option("--format", help="override the detected capture format"),
    ] = None,
    *,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Find the speed window that reads clean, and the centre to settle on."""
    settings: list[Setting] = []
    band = accept_band()
    for path in captures:
        report = analyse_intervals(_intervals(path, fmt))
        rate = report.bit_rate_hz
        readable = band.holds(rate) and report.coherent
        settings.append(
            Setting(
                label=path.stem,
                bit_rate_hz=rate,
                margin=report.worst_margin,
                errors=0 if readable else 1,
            )
        )

    sweep = bracket_of(settings)

    if json_output:
        typer.echo(
            as_json(
                {
                    "usable": sweep.usable,
                    "centre": round(sweep.centre or 0.0, 1),
                    "width": round(sweep.width, 5),
                    "health": round(sweep.health, 4),
                    "best": sweep.best.label if sweep.best else None,
                    "settings": [
                        {
                            "label": item.label,
                            "bit_rate_hz": round(item.bit_rate_hz, 1),
                            "margin": round(item.margin, 4),
                            "clean": item.clean,
                        }
                        for item in sweep.ordered
                    ],
                }
            )
        )
        raise typer.Exit(code=0 if sweep.usable else 1)

    for item in sweep.ordered:
        mark = "clean" if item.clean else "bad  "
        typer.echo(
            f"  {mark}  {item.label:<20} {item.bit_rate_hz / 1000:7.2f} kbit/s  "
            f"margin {item.margin:5.1%}"
        )
    typer.echo(sweep.render())
    if sweep.usable:
        typer.echo(f"drive health  {sweep.health:.0%} from a {sweep.width:.1%} wide window")
    raise typer.Exit(code=0 if sweep.usable else 1)


def register(app: typer.Typer) -> None:
    app.command()(tune)
    app.command(name="tune-sweep")(tune_sweep)
