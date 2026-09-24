from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import decode_image, fail
from fdstoolkit.identify.integrity import inspect_disk
from fdstoolkit.quality.calibrate import DriveVerdict, calibrate
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


def calibrate_command(
    reference: Annotated[Path, typer.Argument(help="an image of a known-good disk")],
    read: Annotated[
        list[Path] | None,
        typer.Option("--read", help="a dump of that same disk, repeatable"),
    ] = None,
    *,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Measure the drive's own error rate before blaming a disk for it."""
    expected, _, _, _ = decode_image(reference)
    dumps = [decode_image(path)[0] for path in read or []]

    try:
        profile = calibrate(expected, dumps)
    except ValueError as error:
        raise fail(str(error)) from error

    if json_output:
        typer.echo(
            as_json(
                {
                    "passes": profile.passes,
                    "blocks_compared": profile.blocks_compared,
                    "blocks_wrong": profile.blocks_wrong,
                    "error_rate": round(profile.error_rate, 6),
                    "verdict": profile.verdict.value,
                }
            )
        )
        raise typer.Exit(code=0 if profile.verdict is DriveVerdict.GOOD else 1)

    typer.echo(f"passes        {profile.passes}")
    typer.echo(f"blocks        {profile.blocks_compared}")
    typer.echo(f"misread       {profile.blocks_wrong}")
    typer.echo(f"error rate    {profile.error_rate:.4%}")
    typer.echo(f"verdict       {profile.verdict.value}")
    raise typer.Exit(code=0 if profile.verdict is DriveVerdict.GOOD else 1)


def integrity(
    image: Annotated[Path, typer.Argument(help="the image to inspect")],
    *,
    original_crcs: Annotated[
        bool,
        typer.Option("--original-crcs", help="expect the dump to carry the disk's own CRCs"),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Look for an image that passes its CRCs and is still wrong."""
    disk, _, _, _ = decode_image(image)
    report = inspect_disk(disk, expect_original_crcs=original_crcs)

    if json_output:
        typer.echo(
            as_json(
                {
                    "sound": report.sound,
                    "suspicions": [
                        {"kind": item.kind.value, "side": item.side, "detail": item.detail}
                        for item in report.suspicions
                    ],
                }
            )
        )
        raise typer.Exit(code=0 if report.sound else 1)

    if report.sound:
        typer.echo("sound, nothing suspicious")
        raise typer.Exit(code=0)
    for item in report.suspicions:
        typer.echo(f"side {item.side}: {item.kind.value}, {item.detail}")
    raise typer.Exit(code=1)


def register(app: typer.Typer) -> None:
    app.command()(reads)
    app.command()(grade)
    app.command(name="calibrate")(calibrate_command)
    app.command()(integrity)
