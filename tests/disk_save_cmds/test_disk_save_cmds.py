from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

from drive_double import FaultPlan, SimulatedDrive
from fakes import game_name, seeded
from main_kit import runner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Disk
from fdstoolkit.core.files import extract_files
from fdstoolkit.edit.files import FileSpec, insert_file

if TYPE_CHECKING:
    import pytest

FAKE = seeded(__name__)
GAME = game_name(FAKE)
SAVE: Final = "SAVEDATA"
PLAYED: Final = bytes(range(64))
FRESH: Final = bytes(64)


def _game(save: bytes) -> Disk:
    disk, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True, game_name=GAME))
    for name in ("MAIN", SAVE):
        data = save if name == SAVE else bytes([0xAA]) * 32
        disk = insert_file(
            disk, side=0, spec=FileSpec(name=name, address=0x6000, kind=FileKind.PROGRAM, data=data)
        )
    return disk


def _attach(monkeypatch: pytest.MonkeyPatch, drive: SimulatedDrive) -> SimulatedDrive:
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: drive)
    return drive


def test_a_save_backed_up_then_restored_comes_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    saved = tmp_path / "save.json"
    _attach(monkeypatch, SimulatedDrive(_game(PLAYED)))
    runner.invoke(app, ["save-backup", "-o", str(saved)])
    drive = _attach(monkeypatch, SimulatedDrive(_game(FRESH)))
    before = tmp_path / "before.fds"

    # Act
    result = runner.invoke(app, ["save-restore", str(saved), "--backup", str(before), "--yes"])

    # Assert
    assert result.exit_code == 0, result.output
    assert drive.disk is not None
    assert {entry.name: entry.data for entry in extract_files(drive.disk)}[SAVE] == PLAYED
    assert before.is_file()
    assert result.stdout.rstrip().endswith(
        f"restored file 1 {SAVE} on side 0, read back as written"
    )


def test_a_backup_names_the_file_and_the_game(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _attach(monkeypatch, SimulatedDrive(_game(PLAYED)))
    saved = tmp_path / "save.json"

    # Act
    result = runner.invoke(app, ["save-backup", "-o", str(saved)])

    # Assert
    assert result.exit_code == 0, result.output
    assert result.stdout.rstrip() == (
        f"kept file 1 {SAVE}, 64 bytes, of {GAME} version 0, disk 0 side 0 in {saved}"
    )


def test_a_backup_of_a_side_that_does_not_read_clean_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _attach(
        monkeypatch, SimulatedDrive(_game(PLAYED), plan=FaultPlan(bad_crc_blocks=frozenset({3})))
    )
    saved = tmp_path / "save.json"

    # Act
    result = runner.invoke(app, ["save-backup", "-o", str(saved), "--retries", "0"])

    # Assert
    assert result.exit_code == 1
    assert "did not read clean" in result.output
    assert not saved.exists()


def test_a_restore_onto_another_game_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    saved = tmp_path / "save.json"
    _attach(monkeypatch, SimulatedDrive(_game(PLAYED)))
    runner.invoke(app, ["save-backup", "-o", str(saved)])
    other, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True, game_name="ZZZ"))
    drive = _attach(monkeypatch, SimulatedDrive(other))

    # Act
    result = runner.invoke(app, ["save-restore", str(saved), "--yes"])

    # Assert
    assert result.exit_code == 1
    assert f"the save is from {GAME}" in result.output
    assert drive.write_count == 0


def test_a_restore_from_a_file_that_is_not_a_backup_is_refused(tmp_path: Path) -> None:
    # Arrange
    saved = tmp_path / "save.json"
    saved.write_text("{}", encoding="utf-8")

    # Act
    result = runner.invoke(app, ["save-restore", str(saved), "--yes"])

    # Assert
    assert result.exit_code == 1
    assert "this is not a save backup that disk-save wrote" in result.output


def test_a_restore_that_does_not_read_back_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    saved = tmp_path / "save.json"
    _attach(monkeypatch, SimulatedDrive(_game(PLAYED)))
    runner.invoke(app, ["save-backup", "-o", str(saved)])
    _attach(monkeypatch, LeavesTheLastBlock(_game(FRESH)))

    # Act
    result = runner.invoke(app, ["save-restore", str(saved), "--yes"])

    # Assert
    assert result.exit_code == 1
    assert "side 0: block 6 is old data past the end of the image" in result.stdout


class LeavesTheLastBlock(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        current = self.disk
        assert current is not None
        kept = [block.payload for block in current.sides[side].blocks[-1:]]
        super().write_side(side, [*blocks, *kept])
