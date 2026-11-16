from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from drive_double import SimulatedDrive
from fakes import game_name, seeded
from typer.testing import CliRunner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds
from fdstoolkit.history.entries import DRIVE_ENV, disk_key
from fdstoolkit.history.logbook import LOGBOOK_ENV, EntryKind, history, logbook_path
from fdstoolkit.history.lookup import BOTH, NEITHER, NO_IDENTITY

if TYPE_CHECKING:
    import pytest

FAKE = seeded(__name__)
GAME = game_name(FAKE)

runner = CliRunner()


def _image(tmp_path: Path) -> Path:
    path = tmp_path / "game.fds"
    path.write_bytes(blank_image(sides=1, headered=False, formatted=True, game_name=GAME))
    return path


def _attach(monkeypatch: pytest.MonkeyPatch, image: Path) -> SimulatedDrive:
    disk, _ = fds.decode(image.read_bytes())
    drive = SimulatedDrive(disk)
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: drive)
    return drive


def _disk_id(image: Path) -> str:
    disk, _ = fds.decode(image.read_bytes())
    key = disk_key(disk)
    assert key is not None
    return key.id


def test_a_dump_appends_one_entry_under_the_disk_and_the_drive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    image = _image(tmp_path)
    _attach(monkeypatch, image)
    monkeypatch.setenv(DRIVE_ENV, "hvc-022")

    # Act
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.fds")])

    # Assert
    assert result.exit_code == 0, result.output
    found = history(logbook_path(), disk=_disk_id(image))
    assert [(entry.kind, entry.drive, entry.grade) for entry in found] == [
        (EntryKind.DUMP, "hvc-022", "clean")
    ]
    assert f"logged under {_disk_id(image)} in {logbook_path()}" in result.stderr


def test_a_dump_that_cannot_log_keeps_its_image_and_fails_naming_the_logbook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _attach(monkeypatch, _image(tmp_path))
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"")
    monkeypatch.setenv(LOGBOOK_ENV, str(blocker / "logbook.sqlite3"))
    output = tmp_path / "dump.fds"

    # Act
    result = runner.invoke(app, ["dump", "-o", str(output)])

    # Assert
    assert result.exit_code == 1
    assert output.is_file()
    assert f"could not write the logbook at {blocker / 'logbook.sqlite3'}" in result.output


def test_a_grade_appends_an_entry_under_the_disk(tmp_path: Path) -> None:
    # Arrange
    image = _image(tmp_path)

    # Act
    result = runner.invoke(app, ["grade", str(image), "--json"])

    # Assert
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["grade"] == "clean"
    found = history(logbook_path(), disk=_disk_id(image))
    assert [(entry.kind, entry.drive) for entry in found] == [(EntryKind.GRADE, None)]


def test_a_live_calibration_appends_an_entry_under_the_drive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    image = _image(tmp_path)
    _attach(monkeypatch, image)
    monkeypatch.setenv(DRIVE_ENV, "twin")

    # Act
    result = runner.invoke(app, ["calibrate", "head", "--reference", str(image)])

    # Assert
    assert result.exit_code == 0, result.output
    found = history(logbook_path(), drive="twin")
    assert [(entry.kind, entry.disk, entry.grade) for entry in found] == [
        (EntryKind.CALIBRATION, _disk_id(image), "clean")
    ]


def test_a_calibration_without_a_reference_is_logged_for_the_drive_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _attach(monkeypatch, _image(tmp_path))

    # Act
    result = runner.invoke(app, ["calibrate", "head"])

    # Assert
    assert result.exit_code == 0, result.output
    found = history(logbook_path(), drive="drive")
    assert [(entry.disk, entry.title) for entry in found] == [(None, "the disk in the drive")]


def test_log_shows_the_history_of_a_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    image = _image(tmp_path)
    _attach(monkeypatch, image)
    runner.invoke(app, ["dump", "-o", str(tmp_path / "one.fds")])
    runner.invoke(app, ["dump", "-o", str(tmp_path / "two.fds")])

    # Act
    result = runner.invoke(app, ["log", str(image)])

    # Assert
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == f"{_disk_id(image)} {GAME}"
    assert len([line for line in lines if "  dump  " in line]) == 2
    assert lines[-1].startswith("since the dump of ")
    assert lines[-1].endswith(", no block changed")


def test_log_answers_a_drive_history_as_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    image = _image(tmp_path)
    _attach(monkeypatch, image)
    monkeypatch.setenv(DRIVE_ENV, "twin")
    runner.invoke(app, ["calibrate", "head"])

    # Act
    result = runner.invoke(app, ["log", "--drive", "twin", "--json"])

    # Assert
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["subject"] == "drive twin"
    assert [entry["kind"] for entry in payload["entries"]] == ["calibration"]


def test_log_of_nothing_logged_says_so(tmp_path: Path) -> None:
    # Arrange
    image = _image(tmp_path)

    # Act
    result = runner.invoke(app, ["log", str(image)])

    # Assert
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[-1] == "nothing is logged for this yet"


def test_log_needs_a_disk_or_a_drive(tmp_path: Path) -> None:
    # Arrange
    image = _image(tmp_path)

    # Act
    neither = runner.invoke(app, ["log"])
    both = runner.invoke(app, ["log", str(image), "--drive", "twin"])

    # Assert
    assert (neither.exit_code, both.exit_code) == (1, 1)
    assert NEITHER in neither.output
    assert BOTH in both.output


def test_log_of_an_image_without_disk_information_is_refused(tmp_path: Path) -> None:
    # Arrange
    image = tmp_path / "unformatted.fds"
    image.write_bytes(blank_image(sides=1, headered=False, formatted=False))

    # Act
    result = runner.invoke(app, ["log", str(image)])

    # Assert
    assert result.exit_code == 1
    assert NO_IDENTITY in result.output


def test_log_of_a_logbook_that_cannot_be_read_names_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    store = tmp_path / "broken.sqlite3"
    store.write_bytes(b"not a database, only text that sqlite refuses to open " * 64)
    monkeypatch.setenv(LOGBOOK_ENV, str(store))

    # Act
    result = runner.invoke(app, ["log", "--drive", "twin"])

    # Assert
    assert result.exit_code == 1
    assert f"could not read the logbook at {store}" in result.output
