from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from drive_double import FaultPlan, SimulatedDrive
from fakes import game_name, seeded
from typer.testing import CliRunner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds
from fdstoolkit.history.entries import DRIVE_ENV
from fdstoolkit.history.logbook import LOGBOOK_ENV, EntryKind, history, logbook_path

if TYPE_CHECKING:
    import pytest

FAKE = seeded(__name__)
GAME = game_name(FAKE)

runner = CliRunner()


def _image(tmp_path: Path) -> Path:
    path = tmp_path / "reference.fds"
    path.write_bytes(blank_image(sides=1, headered=False, formatted=True, game_name=GAME))
    return path


def _attach(monkeypatch: pytest.MonkeyPatch, image: Path, plan: FaultPlan | None = None) -> None:
    disk, _ = fds.decode(image.read_bytes())
    drive = SimulatedDrive(disk, plan=plan)
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: drive)


def test_the_first_check_becomes_the_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    image = _image(tmp_path)
    _attach(monkeypatch, image)
    monkeypatch.setenv(DRIVE_ENV, "hvc-022")

    # Act
    result = runner.invoke(app, ["session", "--reference", str(image)])

    # Assert
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[-1] == (
        "first check of drive hvc-022 logged with 0 weak block(s); "
        "the next check compares against it"
    )
    found = history(logbook_path(), drive="hvc-022")
    assert [entry.kind for entry in found] == [EntryKind.CHECK]


def test_a_check_that_needed_retries_after_a_clean_one_warns_of_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    image = _image(tmp_path)
    _attach(monkeypatch, image)
    runner.invoke(app, ["session", "--reference", str(image)])
    _attach(monkeypatch, image, FaultPlan(flaky_blocks={0: 2, 1: 2}))

    # Act
    result = runner.invoke(app, ["session", "--reference", str(image), "--json"])

    # Assert
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["moved"] == [[0, 0], [0, 1]]
    assert payload["ok"] is False
    assert payload["headline"].startswith("the drive moved since the check of ")
    assert payload["headline"].endswith(": 2 block(s) now weak, side 0 block 0, side 0 block 1")


def test_a_check_reading_as_before_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    image = _image(tmp_path)
    _attach(monkeypatch, image)
    runner.invoke(app, ["session"])

    # Act
    result = runner.invoke(app, ["session"])

    # Assert
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[-1].startswith("the drive reads as it did at the check of ")


def test_a_check_with_no_disk_fails_naming_the_fault(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    drive = SimulatedDrive(None)
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: drive)

    # Act
    result = runner.invoke(app, ["session"])

    # Assert
    assert result.exit_code == 1
    assert "no disk in the drive" in result.output
    assert not history(logbook_path(), drive="drive")
    assert drive.closed


def test_a_check_whose_logbook_cannot_be_read_names_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _attach(monkeypatch, _image(tmp_path))
    store = tmp_path / "broken.sqlite3"
    store.write_bytes(b"not a database, only text that sqlite refuses to open " * 64)
    monkeypatch.setenv(LOGBOOK_ENV, str(store))

    # Act
    result = runner.invoke(app, ["session"])

    # Assert
    assert result.exit_code == 1
    assert f"could not read the logbook at {store}" in result.output
