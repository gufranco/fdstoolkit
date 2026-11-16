from __future__ import annotations

import json
from pathlib import Path

from main_kit import runner

from fdstoolkit.cli.main import app


def test_diff_reports_identical_images(single_side: Path) -> None:
    # Arrange
    arguments = ["diff", str(single_side), str(single_side)]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    assert "identical" in result.stdout


def test_diff_reports_a_difference(single_side: Path, image: Path) -> None:
    # Arrange
    arguments = ["diff", str(single_side), str(image)]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 1
    assert "side count" in result.stdout


def test_consensus_merges_identical_dumps(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "merged.fds"

    # Act
    result = runner.invoke(
        app,
        ["consensus", str(single_side), str(single_side), "-o", str(out)],
    )

    # Assert
    assert result.exit_code == 0
    assert out.read_bytes() == single_side.read_bytes()


def test_consensus_needs_two_dumps(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    arguments = ["consensus", str(single_side), "-o", str(tmp_path / "m.fds")]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 1
    assert "at least two" in result.stdout


def test_diff_can_emit_json(single_side: Path) -> None:
    # Arrange
    expected = True

    # Act
    payload = json.loads(
        runner.invoke(app, ["diff", str(single_side), str(single_side), "--json"]).stdout
    )

    # Assert
    assert payload["identical"] is expected


def test_diff_lists_the_blocks_that_differ(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    other = tmp_path / "other.fds"
    data = bytearray(single_side.read_bytes())
    data[57] = 0x01
    other.write_bytes(bytes(data))

    # Act
    result = runner.invoke(app, ["diff", str(single_side), str(other)])

    # Assert
    assert result.exit_code == 1
    assert "side 0 block" in result.stdout


def test_consensus_reports_a_disagreement(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    other = tmp_path / "other.fds"
    data = bytearray(single_side.read_bytes())
    data[57] = 0x01
    other.write_bytes(bytes(data))

    # Act
    result = runner.invoke(
        app,
        ["consensus", str(single_side), str(other), "-o", str(tmp_path / "merged.fds")],
    )

    # Assert
    assert result.exit_code == 1
    assert "disagree" in result.stdout


def test_diff_explains_two_identical_images(image: Path) -> None:
    # Arrange
    arguments = ["diff", str(image), str(image), "--explain"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    assert result.stdout.startswith("identical")


def test_diff_explains_a_changed_field(image: Path, tmp_path: Path) -> None:
    # Arrange
    other = tmp_path / "other.fds"
    runner.invoke(app, ["set", str(image), "-o", str(other), "--set", "game_version=2"])

    # Act
    result = runner.invoke(app, ["diff", str(image), str(other), "--explain"])

    # Assert
    assert result.exit_code == 1
    assert "different software" in result.stdout
    assert "game_version (identity): 0x00 against 0x02" in result.stdout


def test_diff_can_explain_as_json(image: Path, tmp_path: Path) -> None:
    # Arrange
    other = tmp_path / "other.fds"
    runner.invoke(app, ["set", str(image), "-o", str(other), "--set", "rewrite_count=3"])

    # Act
    payload = json.loads(
        runner.invoke(app, ["diff", str(image), str(other), "--explain", "--json"]).stdout
    )

    # Assert
    assert payload["same_software"]
    assert payload["fields"][0]["field"] == "rewrite_count"


def test_consensus_prints_a_stability_map(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    other = tmp_path / "second.fds"
    other.write_bytes(single_side.read_bytes())
    output = tmp_path / "merged.fds"

    # Act
    result = runner.invoke(
        app, ["consensus", str(single_side), str(other), "-o", str(output), "--map"]
    )

    # Assert
    assert result.exit_code == 0
    assert "disk_info" in result.stdout
    assert "100.0%" in result.stdout


def test_diff_explains_a_file_difference(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "main.prg"
    payload.write_bytes(bytes([0xAA]) * 8)
    other = tmp_path / "with-file.fds"
    runner.invoke(
        app,
        [
            "insert",
            str(single_side),
            "-o",
            str(other),
            "--file",
            str(payload),
            "--name",
            "MAIN",
        ],
    )

    # Act
    result = runner.invoke(app, ["diff", str(single_side), str(other), "--explain"])

    # Assert
    assert result.exit_code == 1
    assert "file 0 MAIN: added, 8 bytes" in result.stdout
