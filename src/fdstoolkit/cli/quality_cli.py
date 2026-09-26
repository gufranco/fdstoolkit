from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import Family, decode_image, fail, load_captures
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.drive.align import good_block
from fdstoolkit.drive.captures import Bundle
from fdstoolkit.drive.recovery import rebuild
from fdstoolkit.drive.weak import bundle_weak_blocks
from fdstoolkit.quality.confidence import score_disk
from fdstoolkit.quality.grade import grade_disk
from fdstoolkit.quality.reads import compare_reads
from fdstoolkit.report import as_json


def _weak_report(bundle: Bundle, *, json_output: bool) -> None:
    found = bundle_weak_blocks(bundle)
    if json_output:
        typer.echo(
            as_json(
                {
                    "reads": len(bundle.captures),
                    "weak": [
                        {
                            "side": side,
                            "block": entry.block,
                            "kind": entry.kind,
                            "unstable": entry.unstable,
                            "invalid": entry.invalid,
                            "reads": entry.reads,
                            "missing": entry.missing,
                        }
                        for side, entry in found
                    ],
                }
            )
        )
        raise typer.Exit(code=0 if not found else 1)
    typer.echo(f"saved reads   {len(bundle.captures)}")
    typer.echo(f"weak blocks   {len(found)}")
    for side, entry in found:
        typer.echo(f"side {side} {entry.render()}")
    raise typer.Exit(code=0 if not found else 1)


def reads(
    images: Annotated[
        list[Path] | None, typer.Argument(help="two or more dumps of one disk")
    ] = None,
    *,
    captures: Annotated[
        Path | None,
        typer.Option("--captures", help="map the weak blocks in the captures a dump --raw kept"),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Compare repeated dumps of one disk and report which blocks move."""
    if captures is not None:
        _weak_report(load_captures(captures), json_output=json_output)
    disks = [decode_image(path)[0] for path in images or []]

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
                    "missing": [list(item) for item in stats.missing],
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
    for side, block, absent in stats.missing:
        typer.echo(f"side {side} block {block:3d}  missing from {absent} read(s)")
    raise typer.Exit(code=0 if not stats.unstable_blocks else 1)


def _weak_count(disk: Disk, bundle: Bundle) -> int:
    rebuilt = rebuild(bundle).disk
    for index, (ours, theirs) in enumerate(zip(disk.sides, rebuilt.sides, strict=False)):
        if _differ(ours, theirs):
            message = (
                f"the captures are of another disk: their side {index} disk information "
                "differs from the image's"
            )
            raise fail(message)
    return len(bundle_weak_blocks(bundle))


def _differ(ours: Side, theirs: Side) -> bool:
    if not (ours.blocks and theirs.blocks and good_block(theirs.blocks[0])):
        return False
    return ours.blocks[0].payload != theirs.blocks[0].payload


def grade(
    image: Annotated[Path, typer.Argument(help="the image to grade")],
    read: Annotated[
        list[Path] | None,
        typer.Option("--read", help="another dump of the same disk, repeatable"),
    ] = None,
    *,
    captures: Annotated[
        Path | None,
        typer.Option("--captures", help="count the weak blocks in the captures a dump --raw kept"),
    ] = None,
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

    weak = None if captures is None else _weak_count(disk, load_captures(captures))
    report = grade_disk(confidence=confidence, findings=findings, reads=stats, weak_blocks=weak)

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
