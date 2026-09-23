from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from fdstoolkit.cli.main import app
from fdstoolkit.drive.spec import NOMINAL_BIT_RATE_HZ

runner = CliRunner()


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "src.fds"
    runner.invoke(app, ["blank", "-o", str(path), "--sides", "1", "--formatted"])
    return path


def test_a_simulated_dump_keeps_a_class_capture(tmp_path: Path) -> None:
    source = _source(tmp_path)
    raw = tmp_path / "raw"

    result = runner.invoke(
        app,
        ["dump", "-o", str(tmp_path / "d.fds"), "--source", str(source), "--raw", str(raw)],
    )

    assert result.exit_code == 0
    assert "packed pulse classes" in result.stdout
    assert list(raw.glob("*.raw03"))


def test_a_class_capture_can_be_judged(tmp_path: Path) -> None:
    source = _source(tmp_path)
    raw = tmp_path / "raw"
    runner.invoke(
        app,
        ["dump", "-o", str(tmp_path / "d.fds"), "--source", str(source), "--raw", str(raw)],
    )

    capture = next(iter(raw.glob("*.raw03")))
    result = runner.invoke(app, ["classes", str(capture)])

    assert result.exit_code in {0, 1}
    assert "short" in result.stdout


def test_a_simulated_rate_produces_a_timing_capture(tmp_path: Path) -> None:
    source = _source(tmp_path)
    raw = tmp_path / "raw"

    result = runner.invoke(
        app,
        [
            "dump",
            "-o",
            str(tmp_path / "d.fds"),
            "--source",
            str(source),
            "--raw",
            str(raw),
            "--simulated-rate",
            str(NOMINAL_BIT_RATE_HZ),
        ],
    )

    assert result.exit_code == 0
    assert "interval counts" in result.stdout
    assert list(raw.glob("*.counts"))


def test_a_drive_standing_in_at_nominal_tunes_as_settled(tmp_path: Path) -> None:
    source = _source(tmp_path)
    raw = tmp_path / "raw"
    runner.invoke(
        app,
        [
            "dump",
            "-o",
            str(tmp_path / "d.fds"),
            "--source",
            str(source),
            "--raw",
            str(raw),
            "--simulated-rate",
            str(NOMINAL_BIT_RATE_HZ),
        ],
    )

    capture = next(iter(raw.glob("*.counts")))
    result = runner.invoke(app, ["tune", str(capture)])

    assert result.exit_code == 0
    assert "settled" in result.stdout


def test_a_drive_standing_in_slow_is_told_to_speed_up(tmp_path: Path) -> None:
    source = _source(tmp_path)
    raw = tmp_path / "raw"
    runner.invoke(
        app,
        [
            "dump",
            "-o",
            str(tmp_path / "d.fds"),
            "--source",
            str(source),
            "--raw",
            str(raw),
            "--simulated-rate",
            str(NOMINAL_BIT_RATE_HZ * 0.88),
        ],
    )

    capture = next(iter(raw.glob("*.counts")))
    result = runner.invoke(app, ["tune", str(capture)])

    assert result.exit_code == 1
    assert "out of spec" in result.stdout
    assert "counter-clockwise" in result.stdout


def test_a_sweep_across_simulated_settings_finds_the_centre(tmp_path: Path) -> None:
    source = _source(tmp_path)
    captures: list[str] = []
    for index, factor in enumerate((0.96, 1.0, 1.04)):
        raw = tmp_path / f"raw{index}"
        runner.invoke(
            app,
            [
                "dump",
                "-o",
                str(tmp_path / f"d{index}.fds"),
                "--source",
                str(source),
                "--raw",
                str(raw),
                "--simulated-rate",
                str(NOMINAL_BIT_RATE_HZ * factor),
            ],
        )
        captures.append(str(next(iter(raw.glob("*.counts")))))

    result = runner.invoke(app, ["tune-sweep", *captures])

    assert result.exit_code == 0
    assert "window" in result.stdout
    assert "drive health" in result.stdout


def test_a_negative_simulated_rate_is_refused(tmp_path: Path) -> None:
    source = _source(tmp_path)

    result = runner.invoke(
        app,
        [
            "dump",
            "-o",
            str(tmp_path / "d.fds"),
            "--source",
            str(source),
            "--simulated-rate",
            "-1",
        ],
    )

    assert result.exit_code == 1
    assert "positive" in result.stdout
