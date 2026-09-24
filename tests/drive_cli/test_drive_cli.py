from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from fdstoolkit.cli.main import app
from fdstoolkit.codecs.raw import pack_raw03

runner = CliRunner()


def test_a_class_capture_is_judged_on_what_it_can_answer(tmp_path: Path) -> None:
    path = tmp_path / "classes.raw"
    path.write_bytes(pack_raw03(bytes([0] * 740 + [1] * 190 + [2] * 70)))

    result = runner.invoke(app, ["classes", str(path)])

    assert result.exit_code == 0
    assert "healthy" in result.stdout


def test_a_glitching_class_capture_fails(tmp_path: Path) -> None:
    path = tmp_path / "classes.raw"
    path.write_bytes(pack_raw03(bytes([0] * 700 + [1] * 190 + [2] * 60 + [3] * 50)))

    result = runner.invoke(app, ["classes", str(path)])

    assert result.exit_code == 1
    assert "glitch" in result.stdout


def test_class_output_can_be_json(tmp_path: Path) -> None:
    path = tmp_path / "classes.raw"
    path.write_bytes(pack_raw03(bytes([0] * 740 + [1] * 190 + [2] * 70)))

    result = runner.invoke(app, ["classes", str(path), "--json"])

    assert json.loads(result.stdout)["reading"] == "healthy"


def test_a_missing_class_capture_is_refused(tmp_path: Path) -> None:
    result = runner.invoke(app, ["classes", str(tmp_path / "nothing.raw")])

    assert result.exit_code == 1
    assert "file not found" in result.stdout


def test_an_empty_class_capture_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "empty.raw"
    path.write_bytes(b"")

    result = runner.invoke(app, ["classes", str(path)])

    assert result.exit_code == 1


def test_a_console_reading_at_target_needs_no_adjustment() -> None:
    result = runner.invoke(app, ["reading", "148"])

    assert result.exit_code == 0
    assert "leave the motor speed alone" in result.stdout


def test_a_high_console_reading_means_run_faster() -> None:
    result = runner.invoke(app, ["reading", "155"])

    assert result.exit_code == 1
    assert "raise the motor speed" in result.stdout
    assert "clockwise" not in result.stdout


def test_a_low_console_reading_means_run_slower() -> None:
    result = runner.invoke(app, ["reading", "140"])

    assert result.exit_code == 1
    assert "lower the motor speed" in result.stdout
    assert "clockwise" not in result.stdout


def test_a_console_reading_can_be_json() -> None:
    result = runner.invoke(app, ["reading", "148", "--json"])

    payload = json.loads(result.stdout)
    assert payload["verdict"] == "fine"
    assert payload["direction"] == "hold"
    assert "turn" not in payload


def test_a_console_reading_of_zero_is_refused() -> None:
    result = runner.invoke(app, ["reading", "0"])

    assert result.exit_code == 1
    assert "positive" in result.stdout
