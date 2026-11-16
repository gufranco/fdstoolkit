from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import Family, YesOption, fail, side_count, writer_for
from fdstoolkit.cli.hardware_cmds import BackupOption, open_drive, prompter, step
from fdstoolkit.hardware.fdsstick import FdsStick
from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.hardware.session import MAX_PASSES, SideFlipError, WriteRefusedError
from fdstoolkit.quality.surface import (
    Finish,
    SurfacePlan,
    SurfaceReport,
    SurfaceTestRefusedError,
    surface_test,
)

TestedSidesOption = Annotated[
    int, typer.Option("--sides", parser=side_count, help="1 or 2 sides to test")
]


CyclesOption = Annotated[
    int,
    typer.Option("--passes", min=1, max=MAX_PASSES, help="how many times to run the pattern cycle"),
]


QuickOption = Annotated[
    bool, typer.Option("--quick", help="write one 4 KiB file per side instead of filling it")
]


FinishOption = Annotated[
    Finish, typer.Option("--finish", help="what to leave on the disk when the test ends")
]


def _tested(
    drive: FdsStick,
    *,
    sides: int,
    ask: Callable[[str], bool],
    backup: Path | None,
    plan: SurfacePlan,
) -> SurfaceReport:
    try:
        return surface_test(
            drive,
            drive,
            sides=sides,
            confirm=ask,
            flip=ask,
            progress=step,
            backup=None if backup is None else writer_for(backup),
            plan=plan,
        )
    except (HardwareFaultError, WriteRefusedError, SideFlipError, SurfaceTestRefusedError) as error:
        raise fail(str(error)) from error


def surface(
    *,
    sides: TestedSidesOption = 1,
    backup: BackupOption = None,
    passes: CyclesOption = 1,
    quick: QuickOption = False,
    finish: FinishOption = Finish.LEAVE,
    yes: YesOption = False,
) -> None:
    plan = SurfacePlan(rounds=passes, fill=not quick, finish=finish)
    with closing(open_drive()) as drive:
        report = _tested(drive, sides=sides, ask=prompter(yes=yes), backup=backup, plan=plan)
        report_surface(report)
        typer.echo(f"grade {report.grade}")
        raise typer.Exit(code=0 if report.passed else 1)


def _surface_counts(report: SurfaceReport) -> None:
    if report.hard_blocks:
        typer.echo(
            f"{len(report.hard_blocks)} block(s) failed on more than one pattern, "
            "which is the surface itself",
        )
    if report.transient_blocks:
        typer.echo(
            f"{len(report.transient_blocks)} block(s) failed once, marginal rather than dead",
        )
    if report.recovered_blocks:
        typer.echo(
            f"{len(report.recovered_blocks)} block(s) failed early and read clean after, "
            "so rewriting refreshed them",
        )


def report_surface(report: SurfaceReport) -> None:
    typer.echo(
        f"{report.data_bytes} data bytes per side, {report.coverage:.1%} of the most any "
        f"measured factory side carries, {len(report.passes)} pattern pass(es) run",
    )
    for entry in report.passes:
        state = "held" if entry.verified else "did not hold"
        typer.echo(f"side {entry.side} pass {entry.round} pattern {entry.pattern}: {state}")
    if report.pulse_summary:
        typer.echo(report.pulse_summary)
    _surface_counts(report)
    if report.stopped is not None:
        typer.echo(f"stopped early: {report.stopped.value}")
    if report.refusal:
        typer.echo(f"  {report.refusal}")
    for line in (report.wear_hint, report.advice):
        if line:
            typer.echo(line)
    _report_finish(report)


def _report_finish(report: SurfaceReport) -> None:
    if report.finish is not Finish.LEAVE and not report.finish_ran:
        typer.echo("the finish was skipped because the test stopped early")
    elif report.finish is not Finish.LEAVE:
        left = (
            "formatted as it leaves the kiosk"
            if report.finish is Finish.BLANK
            else "erased, with nothing the adapter can read"
        )
        state = "verified" if report.finish_verified else "which did not verify"
        typer.echo(f"left the disk {left}, {state}")
    if report.finish_problem:
        typer.echo(f"  {report.finish_problem}")


def register(app: typer.Typer) -> None:
    app.command(
        rich_help_panel=Family.HARDWARE,
        help="Write and read back every pulse length to grade a scratch disk.",
    )(surface)
