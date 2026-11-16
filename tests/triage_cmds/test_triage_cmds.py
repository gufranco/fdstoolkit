from __future__ import annotations

import json
from pathlib import Path

from capture_fixture import CREATED, IMAGE, captures_of, disk_with_a_file
from typer.testing import CliRunner

from fdstoolkit.cli.main import app
from fdstoolkit.drive.captures import write_bundle
from fdstoolkit.drive.triage import ONE_DISK

runner = CliRunner()


def _bundle(folder: Path, offsets: tuple[int | None, ...]) -> Path:
    write_bundle(folder, captures_of(disk_with_a_file(), offsets), image=IMAGE, created=CREATED)
    return folder


def test_a_failure_on_every_disk_names_the_drive_and_fails(tmp_path: Path) -> None:
    # Arrange
    first = _bundle(tmp_path / "first", (None, 10, None))
    second = _bundle(tmp_path / "second", (None, 10, None))

    # Act
    result = runner.invoke(app, ["triage", str(first), str(second)])

    # Assert
    assert result.exit_code == 1
    lines = result.stdout.splitlines()
    assert lines[0] == "2 disks, 1 position(s) fail on every disk: the drive"
    assert lines[1].endswith(f"fails on every disk ({first}, {second}), so it is the drive")


def test_a_failure_on_one_disk_passes_and_answers_as_json(tmp_path: Path) -> None:
    # Arrange
    first = _bundle(tmp_path / "first", (None, 10, None))
    second = _bundle(tmp_path / "second", (None, None))

    # Act
    result = runner.invoke(app, ["triage", str(first), str(second), "--json"])

    # Assert
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [zone["culprit"] for zone in payload["zones"]] == ["disk"]
    assert payload["ok"] is True


def test_one_bundle_is_refused(tmp_path: Path) -> None:
    # Arrange
    only = _bundle(tmp_path / "only", (None, 10, None))

    # Act
    result = runner.invoke(app, ["triage", str(only)])

    # Assert
    assert result.exit_code == 1
    assert ONE_DISK in result.output
