from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from drive_double import SimulatedDrive
from fakes import game_name, seeded
from main_kit import attach, runner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds
from fdstoolkit.quality.checker import CHECKER_ALONE, CHECKER_BYTES

if TYPE_CHECKING:
    import pytest

FAKE = seeded(__name__)
GAME = game_name(FAKE)


def test_a_quick_surface_test_grades_a_good_scratch_disk_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    image = tmp_path / "scratch.fds"
    image.write_bytes(blank_image(sides=1, headered=False, formatted=True, game_name=GAME))
    attach(monkeypatch, image)

    # Act
    result = runner.invoke(app, ["surface", "--quick", "--yes"])

    # Assert
    assert result.exit_code == 0, result.output
    assert result.stdout.rstrip().endswith("grade clean")


def test_the_checker_pattern_writes_type_5_blocks_and_reads_them_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    image = tmp_path / "scratch.fds"
    image.write_bytes(blank_image(sides=1, headered=False, formatted=True, game_name=GAME))
    drive = attach(monkeypatch, image)
    backup = tmp_path / "before.fds"

    # Act
    result = runner.invoke(
        app, ["surface", "--pattern", "checker", "--backup", str(backup), "--yes"]
    )

    # Assert
    assert result.exit_code == 0, result.output
    assert result.stdout.rstrip().endswith(f"side 0: all {CHECKER_BYTES} pattern bytes read back")
    assert backup.read_bytes() == image.read_bytes()
    assert drive.write_count == 1


def test_the_checker_pattern_takes_none_of_the_cycle_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    image = tmp_path / "scratch.fds"
    image.write_bytes(blank_image(sides=1, headered=False, formatted=True, game_name=GAME))
    drive = attach(monkeypatch, image)

    # Act
    result = runner.invoke(app, ["surface", "--pattern", "checker", "--quick", "--yes"])

    # Assert
    assert result.exit_code == 1
    assert CHECKER_ALONE in result.output
    assert drive.write_count == 0


def test_a_checker_on_a_protected_disk_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    disk, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True, game_name=GAME))
    drive = SimulatedDrive(disk, write_protected=True)
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: drive)

    # Act
    result = runner.invoke(app, ["surface", "--pattern", "checker", "--yes"])

    # Assert
    assert result.exit_code == 1
    assert "write protected" in result.output


class DropsTheTestBlock(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        super().write_side(side, blocks[:-1])


def test_a_checker_side_that_does_not_read_back_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    disk, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True, game_name=GAME))
    monkeypatch.setattr(
        "fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: DropsTheTestBlock(disk)
    )

    # Act
    result = runner.invoke(app, ["surface", "--pattern", "checker", "--yes"])

    # Assert
    assert result.exit_code == 1
    assert result.stdout.rstrip().endswith("no type 5 test block read back")
