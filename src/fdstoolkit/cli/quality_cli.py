from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import Family, JsonOption, decode_image, fail, load_captures
from fdstoolkit.core.diagnostics import Diagnostic
from fdstoolkit.core.disk import Disk
from fdstoolkit.drive.captures import Bundle
from fdstoolkit.drive.pulse import bundle_findings
from fdstoolkit.drive.recognition import rate_lines, read_rates
from fdstoolkit.drive.recovery import captures_of_another_disk
from fdstoolkit.drive.weak import WeakBlock, bundle_weak_blocks
from fdstoolkit.hardware.session import Grade
from fdstoolkit.quality.confidence import ConfidenceReport, score_disk
from fdstoolkit.quality.grade import GradedReport, grade_disk
from fdstoolkit.quality.reads import ReadStatistics, compare_reads
from fdstoolkit.report import as_json


def _weak_payload(bundle: Bundle, found: tuple[tuple[int, WeakBlock], ...]) -> dict[str, object]:
    weak = [
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
    ]
    rates = [
        {
            "side": rate.side,
            "read": rate.read,
            "rate": round(rate.recognition.rate, 6),
            "counted": rate.recognition.counted,
            "unclassed": rate.recognition.unclassed,
            "span": rate.recognition.span.value,
        }
        for rate in read_rates(bundle.captures)
    ]
    return {"reads": len(bundle.captures), "weak": weak, "rates": rates}


def _weak_report(bundle: Bundle, *, json_output: bool) -> None:
    found = bundle_weak_blocks(bundle)
    if json_output:
        typer.echo(as_json(_weak_payload(bundle, found)))
        raise typer.Exit(code=0 if not found else 1)
    typer.echo(f"saved reads   {len(bundle.captures)}")
    for line in rate_lines(bundle.captures):
        typer.echo(line)
    typer.echo(f"weak blocks   {len(found)}")
    for side, entry in found:
        typer.echo(f"side {side} {entry.render()}")
    raise typer.Exit(code=0 if not found else 1)


DumpsArgument = Annotated[list[Path] | None, typer.Argument(help="two or more dumps of one disk")]
WeakCapturesOption = Annotated[
    Path | None,
    typer.Option("--captures", help="map the weak blocks in the captures a dump --raw kept"),
]
GradedArgument = Annotated[Path, typer.Argument(help="the image to grade")]
ReadOption = Annotated[
    list[Path] | None, typer.Option("--read", help="another dump of the same disk, repeatable")
]
CountedCapturesOption = Annotated[
    Path | None,
    typer.Option("--captures", help="count the weak blocks in the captures a dump --raw kept"),
]
MapOption = Annotated[bool, typer.Option("--map", help="print the per-block confidence")]


def _compared(disks: list[Disk]) -> ReadStatistics:
    try:
        return compare_reads(disks)
    except ValueError as error:
        raise fail(str(error)) from error


def _reads_payload(stats: ReadStatistics) -> dict[str, object]:
    return {
        "passes": stats.passes,
        "stability": round(stats.stability, 6),
        "decay": stats.decay.value,
        "ones_lost": stats.ones_lost,
        "ones_gained": stats.ones_gained,
        "unstable": [list(item) for item in stats.unstable_blocks],
        "missing": [list(item) for item in stats.missing],
    }


def _print_reads(stats: ReadStatistics) -> None:
    typer.echo(f"passes        {stats.passes}")
    typer.echo(f"stability     {stats.stability:.2%}")
    typer.echo(f"decay         {stats.decay.value}")
    typer.echo(f"bits lost     {stats.ones_lost}")
    typer.echo(f"bits gained   {stats.ones_gained}")
    for item in (entry for entry in stats.blocks if not entry.stable):
        typer.echo(
            f"side {item.side} block {item.block:3d}  {item.kind:<11} "
            f"{item.variants} variants, {item.flip_rate:.1%} flip rate, "
            f"{item.bits_differing} bits"
        )
    for side, block, absent in stats.missing:
        typer.echo(f"side {side} block {block:3d}  missing from {absent} read(s)")


def reads(
    images: DumpsArgument = None,
    *,
    captures: WeakCapturesOption = None,
    json_output: JsonOption = False,
) -> None:
    if captures is not None:
        _weak_report(load_captures(captures), json_output=json_output)
    stats = _compared([decode_image(path)[0] for path in images or []])
    if json_output:
        typer.echo(as_json(_reads_payload(stats)))
    else:
        _print_reads(stats)
    raise typer.Exit(code=0 if not stats.unstable_blocks else 1)


def _weak_count(disk: Disk, bundle: Bundle) -> int:
    foreign = captures_of_another_disk(disk, bundle)
    if foreign:
        raise fail(foreign)
    return len(bundle_weak_blocks(bundle))


def _graded(
    disk: Disk, findings: tuple[Diagnostic, ...], read: list[Path] | None, captures: Path | None
) -> tuple[GradedReport, ConfidenceReport, tuple[Diagnostic, ...]]:
    stats = _compared([disk, *[decode_image(path)[0] for path in read]]) if read else None
    confidence = score_disk(disk, reads=stats)
    bundle = None if captures is None else load_captures(captures)
    weak = None if bundle is None else _weak_count(disk, bundle)
    pulse = () if bundle is None else bundle_findings(bundle.captures)
    report = grade_disk(
        confidence=confidence, findings=(*findings, *pulse), reads=stats, weak_blocks=weak
    )
    return report, confidence, pulse


def _grade_payload(report: GradedReport) -> dict[str, object]:
    reasons = [
        {
            "metric": reason.metric,
            "value": reason.value,
            "threshold": reason.threshold,
            "passed": reason.passed,
        }
        for reason in report.reasons
    ]
    return {
        "grade": report.grade.value,
        "confidence": round(report.confidence, 6),
        "reasons": reasons,
    }


def _print_grade(
    report: GradedReport,
    confidence: ConfidenceReport,
    pulse: tuple[Diagnostic, ...],
    *,
    block_map: bool,
) -> None:
    typer.echo(report.render())
    for finding in pulse:
        typer.echo(f"  {finding.render()}")
    for reason in report.reasons:
        mark = "ok " if reason.passed else "bad"
        typer.echo(f"  {mark}  {reason.render()}")
    for item in confidence.blocks if block_map else ():
        typer.echo(
            f"side {item.side} block {item.block:3d}  {item.kind:<11} "
            f"{item.confidence:6.1%}  {', '.join(item.basis)}"
        )


def grade(
    image: GradedArgument,
    read: ReadOption = None,
    *,
    captures: CountedCapturesOption = None,
    block_map: MapOption = False,
    json_output: JsonOption = False,
) -> None:
    disk, findings, _, _ = decode_image(image)
    report, confidence, pulse = _graded(disk, findings, read, captures)
    if json_output:
        typer.echo(as_json(_grade_payload(report)))
    else:
        _print_grade(report, confidence, pulse, block_map=block_map)
    raise typer.Exit(code=0 if report.grade is Grade.CLEAN else 1)


def register(app: typer.Typer) -> None:
    app.command(
        rich_help_panel=Family.CHECK,
        help="Compare repeated dumps of one disk and report which blocks move.",
    )(reads)
    app.command(
        rich_help_panel=Family.CHECK,
        help="Grade an image and state the measurement behind the grade.",
    )(grade)
