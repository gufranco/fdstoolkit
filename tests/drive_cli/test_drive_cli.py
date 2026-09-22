from __future__ import annotations

import json
import math
from pathlib import Path

from typer.testing import CliRunner

from fdstoolkit.cli.main import app
from fdstoolkit.drive.spec import NOMINAL_BIT_RATE_HZ, cell_from_bit_rate
from fdstoolkit.flux.counts import write_counts
from fdstoolkit.flux.model import FluxCapture, FluxTrack, Revolution, Source

runner = CliRunner()
RATIOS = (1.0, 1.5, 2.0)


def _write(path: Path, *, rate: float = NOMINAL_BIT_RATE_HZ, wow: float = 0.0) -> Path:
    cell = cell_from_bit_rate(rate)
    intervals = tuple(
        round(cell * (1 + wow * math.sin(2 * math.pi * index / 900)) * RATIOS[index % 3])
        for index in range(6_000)
    )
    capture = FluxCapture(
        source=Source.FDSSTICK,
        tracks=(FluxTrack(index=0, revolutions=(Revolution(intervals=intervals),)),),
    )
    path.write_bytes(write_counts(capture))
    return path


def test_a_dialled_in_drive_reports_settled(tmp_path: Path) -> None:
    result = runner.invoke(app, ["tune", str(_write(tmp_path / "a.raw"))])

    assert result.exit_code == 0
    assert "settled" in result.stdout


def test_a_drive_out_of_spec_reports_a_coarse_action(tmp_path: Path) -> None:
    path = _write(tmp_path / "a.raw", rate=NOMINAL_BIT_RATE_HZ * 0.85)

    result = runner.invoke(app, ["tune", str(path)])

    assert result.exit_code == 1
    assert "coarse" in result.stdout
    assert "motor speed" in result.stdout


def test_a_drive_inside_spec_still_reports_a_fine_action(tmp_path: Path) -> None:
    path = _write(tmp_path / "a.raw", rate=NOMINAL_BIT_RATE_HZ * 1.04)

    result = runner.invoke(app, ["tune", str(path)])

    assert result.exit_code == 1
    assert "fine" in result.stdout


def test_tuning_can_print_json(tmp_path: Path) -> None:
    result = runner.invoke(app, ["tune", str(_write(tmp_path / "a.raw")), "--json"])

    payload = json.loads(result.stdout)
    assert payload["settled"] is True
    assert payload["speed"]["verdict"] == "fine"
    assert payload["actions"] == []


def test_a_missing_capture_is_refused(tmp_path: Path) -> None:
    result = runner.invoke(app, ["tune", str(tmp_path / "nothing.raw")])

    assert result.exit_code == 1
    assert "file not found" in result.stdout


def test_an_empty_capture_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "empty.raw"
    path.write_bytes(b"")

    result = runner.invoke(app, ["tune", str(path)])

    assert result.exit_code == 1


def test_a_sweep_reports_its_window(tmp_path: Path) -> None:
    low = _write(tmp_path / "low.raw", rate=NOMINAL_BIT_RATE_HZ * 0.97)
    mid = _write(tmp_path / "mid.raw", rate=NOMINAL_BIT_RATE_HZ)
    high = _write(tmp_path / "high.raw", rate=NOMINAL_BIT_RATE_HZ * 1.03)

    result = runner.invoke(app, ["tune-sweep", str(low), str(mid), str(high)])

    assert result.exit_code == 0
    assert "window" in result.stdout
    assert "centre" in result.stdout


def test_a_sweep_can_print_json(tmp_path: Path) -> None:
    low = _write(tmp_path / "low.raw", rate=NOMINAL_BIT_RATE_HZ * 0.97)
    high = _write(tmp_path / "high.raw", rate=NOMINAL_BIT_RATE_HZ * 1.03)

    result = runner.invoke(app, ["tune-sweep", str(low), str(high), "--json"])

    payload = json.loads(result.stdout)
    assert payload["usable"] is True
    assert payload["centre"] > 0
    assert len(payload["settings"]) == 2


def test_a_sweep_of_nothing_is_refused() -> None:
    result = runner.invoke(app, ["tune-sweep"])

    assert result.exit_code != 0


def test_a_sweep_where_nothing_reads_clean_says_so(tmp_path: Path) -> None:
    path = _write(tmp_path / "bad.raw", rate=NOMINAL_BIT_RATE_HZ * 0.5)

    result = runner.invoke(app, ["tune-sweep", str(path)])

    assert result.exit_code == 1
    assert "no setting" in result.stdout
