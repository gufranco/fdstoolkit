from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import fail, guard_output
from fdstoolkit.codecs import fds
from fdstoolkit.core.diagnostics import Severity
from fdstoolkit.flux.analysis import analyse_capture
from fdstoolkit.flux.decode import decode_capture
from fdstoolkit.flux.load import CaptureFormat, detect_format, load_capture
from fdstoolkit.flux.model import FluxCapture
from fdstoolkit.report import as_json


def _load(path: Path, fmt: CaptureFormat | None) -> tuple[FluxCapture, CaptureFormat]:
    if not path.is_file():
        message = f"file not found: {path}"
        raise fail(message)
    data = path.read_bytes()
    try:
        chosen = fmt or detect_format(data)
        return load_capture(data, fmt=chosen), chosen
    except ValueError as error:
        raise fail(str(error)) from error


def flux(
    capture: Annotated[Path, typer.Argument(help="a flux or pulse capture")],
    fmt: Annotated[
        CaptureFormat | None,
        typer.Option("--format", help="override the detected capture format"),
    ] = None,
    *,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Measure a flux capture: bit cell, cluster separation, jitter and speed."""
    loaded, chosen = _load(capture, fmt)
    try:
        report = analyse_capture(loaded)
    except ValueError as error:
        raise fail(str(error)) from error

    if json_output:
        typer.echo(
            as_json(
                {
                    "format": chosen.value,
                    "healthy": report.healthy,
                    "worst_margin": round(report.worst_margin, 4),
                    "worst_track": report.worst_track,
                    "tracks": [
                        {
                            "index": track.index,
                            "revolutions": len(track.revolutions),
                            "worst_margin": round(track.worst_margin, 4),
                            "rpm_spread": round(track.rpm_spread, 4),
                            "bit_rate_hz": round(track.revolutions[0].bit_rate_hz),
                            "base_ns": round(track.revolutions[0].base_ns, 1),
                            "pulses": track.revolutions[0].pulses,
                            "outliers": track.revolutions[0].outliers,
                        }
                        for track in report.tracks
                    ],
                }
            )
        )
        raise typer.Exit(code=0 if report.healthy else 1)

    typer.echo(f"format        {chosen.value}")
    for track in report.tracks:
        first = track.revolutions[0]
        typer.echo(
            f"track {track.index:<3d}     {first.pulses} pulses, "
            f"bit cell {first.base_ns:.0f} ns ({first.bit_rate_hz:.0f} Hz)"
        )
        for label, cluster in enumerate(first.clusters):
            typer.echo(
                f"  class {label}     centre {cluster.centre_ns:8.0f} ns  "
                f"jitter {cluster.spread_ns:6.0f} ns  {cluster.count} pulses"
            )
        for gap in first.separations:
            typer.echo(
                f"  {gap.lower} to {gap.upper}     margin {gap.margin:5.1%} "
                f"at boundary {gap.boundary_ns:.0f} ns"
            )
        if first.rpm is not None:
            typer.echo(f"  speed       {first.rpm:.2f} rpm")
        if first.outliers:
            typer.echo(f"  outliers    {first.outliers}")
    if report.blank:
        typer.echo(f"blank tracks  {len(report.blank)} carry no coherent data")
    typer.echo(f"worst margin  {report.worst_margin:.1%} on track {report.worst_track}")
    typer.echo("verdict       " + ("healthy" if report.healthy else "degraded"))
    raise typer.Exit(code=0 if report.healthy else 1)


def flux_decode(
    capture: Annotated[Path, typer.Argument(help="a flux or pulse capture")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the image")],
    fmt: Annotated[
        CaptureFormat | None,
        typer.Option("--format", help="override the detected capture format"),
    ] = None,
    *,
    fixed: Annotated[
        bool, typer.Option("--fixed", help="use nominal thresholds instead of fitting")
    ] = False,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Decode a flux capture into a disk image."""
    guard_output(output, force=force)
    loaded, _ = _load(capture, fmt)

    try:
        disk, findings = decode_capture(loaded, adaptive=not fixed)
    except ValueError as error:
        raise fail(str(error)) from error

    data, _ = fds.encode(disk, headered=False)
    output.write_bytes(data)

    for finding in findings:
        typer.echo(finding.render())
    typer.echo(f"wrote {output} ({len(data)} bytes)")
    errors = [item for item in findings if item.severity is Severity.ERROR]
    raise typer.Exit(code=1 if errors else 0)


def register(app: typer.Typer) -> None:
    app.command()(flux)
    app.command(name="flux-decode")(flux_decode)
