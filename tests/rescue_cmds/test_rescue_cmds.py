from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Final

from capture_fixture import disk_with_a_file
from drive_double import FaultPlan, SimulatedDrive
from fakes import game_name, seeded
from typer.testing import CliRunner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds
from fdstoolkit.core.disk import Disk
from fdstoolkit.drive.rescue import STATE_NAME, load_folder
from fdstoolkit.hardware.ports import BlockRead

if TYPE_CHECKING:
    import pytest

FAKE = seeded(__name__)
OTHER_GAME = game_name(FAKE)
DAMAGED: Final = 3

runner = CliRunner()


class StopsOnRead(SimulatedDrive):
    def __init__(self, disk: Disk, stop_at: int) -> None:
        super().__init__(disk, plan=FaultPlan(bad_crc_blocks=frozenset({DAMAGED})))
        self._stop_at = stop_at

    def read_side(self, side: int) -> Iterator[BlockRead]:
        if self.read_count + 1 == self._stop_at:
            raise KeyboardInterrupt
        return super().read_side(side)


class Blind(SimulatedDrive):
    @property
    def captures(self) -> tuple[()]:
        return ()


def _attach(monkeypatch: pytest.MonkeyPatch, drive: SimulatedDrive) -> SimulatedDrive:
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: drive)
    return drive


def test_a_first_run_on_a_damaged_disk_keeps_its_reads_and_writes_no_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    folder = tmp_path / "rescue"
    output = tmp_path / "out.fds"
    _attach(
        monkeypatch,
        SimulatedDrive(disk_with_a_file(), plan=FaultPlan(bad_crc_blocks=frozenset({DAMAGED}))),
    )

    # Act
    result = runner.invoke(app, ["rescue", str(folder), "-o", str(output), "--passes", "2"])

    # Assert
    assert result.exit_code == 1, result.output
    assert f"side 0: 1 block(s) unsettled after 2 read(s): {DAMAGED}" in result.stdout
    assert load_folder(folder).reads_of(0) == 2
    assert not output.exists()


def test_a_second_run_that_reads_the_block_clean_writes_the_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    disk = disk_with_a_file()
    folder = tmp_path / "rescue"
    output = tmp_path / "out.fds"
    _attach(monkeypatch, SimulatedDrive(disk, plan=FaultPlan(bad_crc_blocks=frozenset({DAMAGED}))))
    runner.invoke(app, ["rescue", str(folder), "-o", str(output), "--passes", "1"])
    _attach(monkeypatch, SimulatedDrive(disk))

    # Act
    result = runner.invoke(app, ["rescue", str(folder), "-o", str(output), "--passes", "3"])

    # Assert
    assert result.exit_code == 0, result.output
    assert "side 0: every declared block settled after 2 read(s)" in result.stdout
    written, _ = fds.decode(output.read_bytes())
    assert written.sides[0].blocks[DAMAGED].payload == disk.sides[0].blocks[DAMAGED].payload


def test_a_run_on_another_disk_is_refused_and_keeps_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    folder = tmp_path / "rescue"
    output = tmp_path / "out.fds"
    _attach(
        monkeypatch,
        SimulatedDrive(disk_with_a_file(), plan=FaultPlan(bad_crc_blocks=frozenset({DAMAGED}))),
    )
    runner.invoke(app, ["rescue", str(folder), "-o", str(output), "--passes", "1"])
    before = (folder / STATE_NAME).read_bytes()
    other, _ = fds.decode(
        blank_image(sides=1, headered=False, formatted=True, game_name=OTHER_GAME)
    )
    drive = _attach(monkeypatch, SimulatedDrive(other))

    # Act
    result = runner.invoke(app, ["rescue", str(folder), "-o", str(output), "--passes", "3"])

    # Assert
    assert result.exit_code == 1
    assert "this rescue is of " in result.output
    assert drive.read_count == 1
    assert (folder / STATE_NAME).read_bytes() == before
    assert load_folder(folder).reads_of(0) == 1


def test_an_interrupted_run_keeps_every_read_it_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    folder = tmp_path / "rescue"
    _attach(monkeypatch, StopsOnRead(disk_with_a_file(), stop_at=3))

    # Act
    result = runner.invoke(app, ["rescue", str(folder), "-o", str(tmp_path / "out.fds")])

    # Assert
    assert result.exit_code == 1
    assert f"stopped; 2 read(s) of side 0 are kept in {folder}" in result.output
    assert load_folder(folder).reads_of(0) == 2


def test_a_drive_that_returns_no_capture_cannot_be_voted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    folder = tmp_path / "rescue"
    _attach(monkeypatch, Blind(disk_with_a_file()))

    # Act
    result = runner.invoke(app, ["rescue", str(folder), "-o", str(tmp_path / "out.fds")])

    # Assert
    assert result.exit_code == 1
    assert "the drive returned no pulse capture of this read" in result.output
    assert not (folder / STATE_NAME).exists()


def test_a_drive_fault_stops_the_run_and_says_what_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    folder = tmp_path / "rescue"
    _attach(monkeypatch, SimulatedDrive(None))

    # Act
    result = runner.invoke(app, ["rescue", str(folder), "-o", str(tmp_path / "out.fds")])

    # Assert
    assert result.exit_code == 1
    assert "no disk in the drive" in result.output
    assert f"0 read(s) of side 0 are kept in {folder}" in result.output


def test_a_rescue_folder_that_is_broken_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    folder = tmp_path / "rescue"
    folder.mkdir()
    (folder / "manifest.json").write_text("{", encoding="utf-8")
    drive = _attach(monkeypatch, SimulatedDrive(disk_with_a_file()))

    # Act
    result = runner.invoke(app, ["rescue", str(folder), "-o", str(tmp_path / "out.fds")])

    # Assert
    assert result.exit_code == 1
    assert "does not parse" in result.output
    assert drive.read_count == 0
