from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from drive_double import FaultPlan, SimulatedDrive
from main_kit import attach, attach_facing, long_side_image, operator, runner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli import common, hardware_cmds
from fdstoolkit.cli.main import app
from fdstoolkit.hardware.session import Grade
from fdstoolkit.quality.surface import (
    Finish,
    PatternPass,
    StopReason,
    SurfacePattern,
    SurfaceReport,
)

if TYPE_CHECKING:
    import pytest


def test_write_verifies_by_reading_back(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attach(monkeypatch, single_side)
    backup = tmp_path / "before.fds"

    # Act
    result = runner.invoke(
        app,
        ["write", str(single_side), "--backup", str(backup), "--yes"],
    )

    # Assert
    assert result.exit_code == 0
    assert "verified True" in result.stdout
    assert backup.exists()


def test_write_refuses_a_side_longer_than_any_factory_side(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach(monkeypatch, single_side)

    # Act
    result = runner.invoke(app, ["write", str(long_side_image(single_side, tmp_path)), "--yes"])

    # Assert
    assert result.exit_code == 1
    assert "Pass --long-side to write it anyway" in result.stdout
    assert drive.write_count == 0


def test_write_writes_a_long_side_when_told_to(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach(monkeypatch, single_side)
    image = long_side_image(single_side, tmp_path)

    # Act
    result = runner.invoke(app, ["write", str(image), "--yes", "--long-side"])

    # Assert
    assert result.exit_code == 0
    assert drive.write_count == 1


def test_write_stops_when_the_confirmation_is_declined(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attach(monkeypatch, single_side)

    # Act
    result = runner.invoke(app, ["write", str(single_side)], input="n\n")

    # Assert
    assert result.exit_code == 1
    assert "declined" in result.stdout


def test_write_turns_the_disk_once_for_a_two_side_image(
    image: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach_facing(monkeypatch, image)
    monkeypatch.setattr(typer, "confirm", operator(drive, turns=True))

    # Act
    result = runner.invoke(app, ["write", str(image)])

    # Assert
    assert result.exit_code == 0, result.output
    assert "  writing side 1" in result.stderr
    assert drive.turns == 1


def test_write_stops_when_the_turn_is_declined(
    image: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach_facing(monkeypatch, image)
    monkeypatch.setattr(typer, "confirm", operator(drive, turns=False))

    # Act
    result = runner.invoke(app, ["write", str(image)])

    # Assert
    assert result.exit_code == 1
    assert "declined to turn the disk over" in result.stdout


def test_write_reports_a_missing_fdsstick(single_side: Path) -> None:
    # Arrange
    arguments = ["write", str(single_side), "--yes"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 1
    assert "FDSStick" in result.stdout or "hidapi" in result.stdout


def test_write_names_a_block_that_did_not_stick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    source = tmp_path / "source.fds"
    source.write_bytes(blank_image(sides=1, headered=False, formatted=True))
    attach(monkeypatch, source, plan=FaultPlan(unstable_blocks=frozenset({1})))

    # Act
    result = runner.invoke(app, ["write", str(source), "--yes"])

    # Assert
    assert "did not read back as written" in result.stdout


def test_surface_grades_a_healthy_disk(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attach(monkeypatch, single_side)

    # Act
    result = runner.invoke(
        app,
        ["surface", "--yes", "--backup", str(tmp_path / "b.fds")],
    )

    # Assert
    assert result.exit_code == 0
    assert "grade clean" in result.stdout


def test_surface_stops_when_declined(single_side: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    attach(monkeypatch, single_side)

    # Act
    result = runner.invoke(app, ["surface"], input="n\n")

    # Assert
    assert result.exit_code == 1
    assert "declined" in result.stdout


def test_surface_closes_the_drive_when_declined(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach(monkeypatch, single_side)

    # Act
    runner.invoke(app, ["surface"], input="n\n")

    # Assert
    assert drive.closed


def test_surface_runs_without_a_backup(single_side: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    attach(monkeypatch, single_side)

    # Act
    result = runner.invoke(app, ["surface", "--yes"])

    # Assert
    assert result.exit_code == 0


def test_write_warns_when_an_interrupt_lands_mid_write(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    disk, _, _, _ = common.decode_image(single_side)

    class Interrupted(SimulatedDrive):
        def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
            del side, blocks
            raise KeyboardInterrupt

    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: Interrupted(disk))

    # Act
    result = runner.invoke(app, ["write", str(single_side), "--yes"])

    # Assert
    assert result.exit_code == 1
    assert "half written" in result.stdout


def test_write_closes_the_drive(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach(monkeypatch, single_side)

    # Act
    runner.invoke(app, ["write", str(single_side), "--yes", "--backup", str(tmp_path / "b.fds")])

    # Assert
    assert drive.closed


def test_surface_says_why_it_stopped_and_that_the_finish_was_skipped(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attach(monkeypatch, single_side, plan=FaultPlan(writes_do_not_stick=True))

    # Act
    result = runner.invoke(app, ["surface", "--yes", "--finish", "blank"])

    # Assert
    assert result.exit_code == 1
    assert f"stopped early: {StopReason.REFUSED.value}" in result.stdout
    assert "reads back exactly as it was before the write" in result.stdout
    assert "the finish was skipped because the test stopped early" in result.stdout


def test_surface_names_every_class_of_failing_block(capsys: pytest.CaptureFixture[str]) -> None:
    # Arrange
    report = SurfaceReport(
        passes=(
            PatternPass(
                SurfacePattern.SHORT,
                verified=False,
                mismatched_blocks=((0, 4), (0, 9)),
                grade=Grade.FAILED,
                short=30,
                long=1,
                compared=900,
            ),
            PatternPass(
                SurfacePattern.MEDIUM,
                verified=False,
                mismatched_blocks=((0, 4),),
                grade=Grade.FAILED,
                short=12,
                long=0,
                compared=400,
            ),
            PatternPass(
                SurfacePattern.LONG, verified=True, mismatched_blocks=(), grade=Grade.CLEAN
            ),
        ),
        coverage=0.98,
        data_bytes=53854,
        finish=Finish.ERASE,
        finish_verified=False,
        finish_ran=True,
        finish_problem="side 0 reads back exactly what was just written to side 1",
        blocks_per_side=14,
    )
    hardware_cmds.report_surface(report)

    # Act
    result = capsys.readouterr()

    # Assert
    assert "failed on more than one pattern" in result.out
    assert "marginal rather than dead" in result.out
    assert "rewriting refreshed them" in result.out
    assert "erased, with nothing the adapter can read" in result.out
    assert "which did not verify" in result.out
    assert "  side 0 reads back exactly what was just written to side 1" in result.out
    assert "side 0 pass 1 pattern short pulses: did not hold" in result.out
    assert "98.0% of the most any measured factory side carries" in result.out
    assert "42 read short and 1 read long" in result.out
    assert "the drive running fast" in result.out
    assert "the failures are spread across the side" in result.out
    assert "clean the disk surface gently" in result.out
    assert not report.passed
