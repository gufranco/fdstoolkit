from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from fdstoolkit.cli.main import app
from fdstoolkit.codecs.raw import pack_raw03

runner = CliRunner()


def healthy_capture(path: Path) -> Path:
    path.write_bytes(pack_raw03(bytes([0] * 740 + [1] * 190 + [2] * 70)))
    return path


def glitching_capture(path: Path) -> Path:
    path.write_bytes(pack_raw03(bytes([0] * 700 + [1] * 190 + [2] * 60 + [3] * 50)))
    return path


def test_a_healthy_capture_passes(tmp_path: Path) -> None:
    capture = healthy_capture(tmp_path / "side.raw03")

    result = runner.invoke(app, ["calibrate", "--capture", str(capture)])

    assert result.exit_code == 0
    assert "classes" in result.stdout
    assert "healthy" in result.stdout


def test_a_glitching_capture_fails(tmp_path: Path) -> None:
    capture = glitching_capture(tmp_path / "side.raw03")

    result = runner.invoke(app, ["calibrate", "--capture", str(capture)])

    assert result.exit_code == 1
    assert "glitch" in result.stdout


def test_a_missing_capture_is_refused(tmp_path: Path) -> None:
    result = runner.invoke(app, ["calibrate", "--capture", str(tmp_path / "nothing.raw03")])

    assert result.exit_code == 1
    assert "file not found" in result.stdout


def test_an_empty_capture_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "empty.raw03"
    empty.write_bytes(b"")

    result = runner.invoke(app, ["calibrate", "--capture", str(empty)])

    assert result.exit_code == 1
    assert "no pulse class" in result.stdout


def test_a_console_reading_at_target_needs_no_adjustment() -> None:
    result = runner.invoke(app, ["calibrate", "--cycles", "148"])

    assert result.exit_code == 0
    assert "leave the motor speed alone" in result.stdout


def test_a_high_console_reading_means_raise_the_motor_speed() -> None:
    result = runner.invoke(app, ["calibrate", "--cycles", "155"])

    assert result.exit_code == 1
    assert "raise the motor speed" in result.stdout
    assert "clockwise" not in result.stdout


def test_a_low_console_reading_means_lower_the_motor_speed() -> None:
    result = runner.invoke(app, ["calibrate", "--cycles", "140"])

    assert result.exit_code == 1
    assert "lower the motor speed" in result.stdout


def test_a_console_reading_of_zero_is_refused() -> None:
    result = runner.invoke(app, ["calibrate", "--cycles", "0"])

    assert result.exit_code == 1
    assert "positive" in result.stdout


def test_calibrating_with_nothing_to_measure_is_refused() -> None:
    result = runner.invoke(app, ["calibrate"])

    assert result.exit_code == 1
    assert "--cycles, --capture, or both" in result.stdout


def test_both_measurements_must_pass_for_the_drive_to_pass(tmp_path: Path) -> None:
    capture = healthy_capture(tmp_path / "side.raw03")

    result = runner.invoke(app, ["calibrate", "--cycles", "155", "--capture", str(capture)])

    assert result.exit_code == 1
    assert "speed" in result.stdout
    assert "healthy" in result.stdout


def test_both_measurements_can_print_json(tmp_path: Path) -> None:
    capture = healthy_capture(tmp_path / "side.raw03")

    result = runner.invoke(
        app, ["calibrate", "--cycles", "148", "--capture", str(capture), "--json"]
    )

    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert payload["speed"]["verdict"] == "fine"
    assert payload["speed"]["direction"] == "hold"
    assert payload["classes"]["reading"] == "healthy"


def test_one_measurement_leaves_the_other_empty_in_json() -> None:
    result = runner.invoke(app, ["calibrate", "--cycles", "148", "--json"])

    payload = json.loads(result.stdout)
    assert payload["classes"] is None
    assert payload["speed"]["cycles_per_byte"] == 148
