from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from drive_double import FaultPlan, SimulatedDrive
from main_kit import attach, attach_facing, long_side_image, operator, runner

from fdstoolkit.cli import common
from fdstoolkit.cli.main import app

if TYPE_CHECKING:
    import pytest


def test_erase_leaves_a_side_with_no_block_and_keeps_a_backup(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach(monkeypatch, single_side)
    backup = tmp_path / "before.fds"

    # Act
    result = runner.invoke(app, ["erase", "--backup", str(backup), "--yes"])

    # Assert
    assert result.exit_code == 0, result.output
    assert "every side reads back with no block" in result.stdout
    assert drive.disk is not None
    assert drive.disk.sides[0].blocks == ()
    assert backup.read_bytes() == single_side.read_bytes()


def test_erase_turns_the_disk_for_a_second_side(
    two_sides: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach_facing(monkeypatch, two_sides)
    monkeypatch.setattr(typer, "confirm", operator(drive, turns=True))

    # Act
    result = runner.invoke(app, ["erase", "--sides", "2"])

    # Assert
    assert result.exit_code == 0, result.output
    assert drive.disk is not None
    assert [side.blocks for side in drive.disk.sides] == [(), ()]


def test_erase_writes_nothing_without_a_confirmation(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach(monkeypatch, single_side)

    # Act
    result = runner.invoke(app, ["erase"], input="n\n")

    # Assert
    assert result.exit_code == 1
    assert "the operator declined the write" in result.output
    assert drive.write_count == 0


def test_erase_of_a_protected_disk_names_the_tab(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    disk, _, _, _ = common.decode_image(single_side)
    drive = SimulatedDrive(disk, write_protected=True)
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: drive)

    # Act
    result = runner.invoke(app, ["erase", "--yes"])

    # Assert
    assert result.exit_code == 1
    assert "write protected" in result.output
    assert drive.write_count == 0


def test_erase_that_leaves_blocks_behind_fails_naming_them(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    disk, _, _, _ = common.decode_image(single_side)
    drive = SimulatedDrive(disk, plan=FaultPlan(writes_do_not_stick=True))
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: drive)

    # Act
    result = runner.invoke(app, ["erase", "--yes"])

    # Assert
    assert result.exit_code == 1
    assert "did not take the write" in result.output


class LeavesTheLastBlock(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        current = self.disk
        assert current is not None
        kept = [block.payload for block in current.sides[side].blocks[-1:]]
        super().write_side(side, [*blocks, *kept])


def test_erase_that_leaves_an_old_block_names_it_and_fails(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    disk, _, _, _ = common.decode_image(single_side)
    drive = LeavesTheLastBlock(disk)
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: drive)

    # Act
    result = runner.invoke(app, ["erase", "--yes"])

    # Assert
    assert result.exit_code == 1
    assert "side 0: block 0 is old data past the end of the image" in result.stdout
    assert result.stdout.rstrip().endswith("the erase left blocks behind, listed above")


def test_duplicate_writes_each_copy_and_counts_them(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach(monkeypatch, single_side)

    # Act
    result = runner.invoke(app, ["duplicate", str(single_side), "--count", "2", "--yes"])

    # Assert
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[-3:] == [
        "copy 1 of 2: verified, grade clean",
        "copy 2 of 2: verified, grade clean",
        "2 of 2 copies verified",
    ]
    assert drive.write_count == 2


def test_duplicate_that_fails_a_copy_exits_with_the_count(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    disk, _, _, _ = common.decode_image(single_side)
    drive = SimulatedDrive(disk, write_protected=True)
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: drive)

    # Act
    result = runner.invoke(app, ["duplicate", str(single_side), "--yes"])

    # Assert
    assert result.exit_code == 1
    assert "copy 1 of 1: failed, cannot write: disk is write protected" in result.stdout
    assert result.stdout.splitlines()[-1] == "0 of 1 copies verified"


def test_duplicate_refuses_a_side_longer_than_any_factory_side(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach(monkeypatch, single_side)

    # Act
    result = runner.invoke(app, ["duplicate", str(long_side_image(single_side, tmp_path)), "--yes"])

    # Assert
    assert result.exit_code == 1
    assert "longest factory side measured" in result.output
    assert drive.write_count == 0
