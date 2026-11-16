from __future__ import annotations

import json
from pathlib import Path

from capture_fixture import CREATED, DAMAGED, IMAGE, captures_of, disk_with_a_file
from typer.testing import CliRunner

from fdstoolkit.cli.main import app
from fdstoolkit.drive.captures import write_bundle

runner = CliRunner()


def _bundle(tmp_path: Path, offsets: tuple[int | None, ...]) -> Path:
    directory = tmp_path / "captures"
    write_bundle(directory, captures_of(disk_with_a_file(), offsets), image=IMAGE, created=CREATED)
    return directory


def test_track_lists_each_block_and_fails_on_a_weak_one(tmp_path: Path) -> None:
    # Arrange
    bundle = _bundle(tmp_path, (None, 10, None))

    # Act
    result = runner.invoke(app, ["track", str(bundle)])

    # Assert
    assert result.exit_code == 1
    lines = result.stdout.splitlines()
    assert lines[0].startswith("side 0, 3 read(s), ")
    assert lines[0].endswith(", 1 weak")
    assert lines[1 + DAMAGED].endswith("1 pulse(s) differ across 3 read(s), 0 invalid")


def test_track_of_a_steady_side_passes_as_json(tmp_path: Path) -> None:
    # Arrange
    bundle = _bundle(tmp_path, (None, None))

    # Act
    result = runner.invoke(app, ["track", str(bundle), "--json"])

    # Assert
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["side"] == 0
    assert not any(block["weak"] for block in payload["blocks"])


def test_track_of_a_side_the_bundle_never_read_is_refused(tmp_path: Path) -> None:
    # Arrange
    bundle = _bundle(tmp_path, (None,))

    # Act
    result = runner.invoke(app, ["track", str(bundle), "--side", "1"])

    # Assert
    assert result.exit_code == 1
    assert "the captures hold no read of side 1" in result.output
