from __future__ import annotations

import math
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fdstoolkit.cli.main import app
from fdstoolkit.drive.advise import advise
from fdstoolkit.drive.bracket import Bracket
from fdstoolkit.drive.spec import NOMINAL_BIT_RATE_HZ, cell_from_bit_rate
from fdstoolkit.drive.speed import SpeedReport
from fdstoolkit.drive.stability import StabilityReport, measure_stability
from fdstoolkit.flux.analysis import (
    Cluster,
    IntervalReport,
    analyse_intervals,
    refine_base,
    scan_bases,
)
from fdstoolkit.flux.counts import write_counts
from fdstoolkit.flux.model import FluxCapture, FluxTrack, Revolution, Source

runner = CliRunner()
RATIOS = (1.0, 1.5, 2.0)
CELL = cell_from_bit_rate(NOMINAL_BIT_RATE_HZ)


def test_a_bit_rate_of_nothing_has_no_cell() -> None:
    assert cell_from_bit_rate(0) == 0.0


def test_a_report_with_no_rate_has_no_cycle_count() -> None:
    assert SpeedReport(cell_ns=0.0, family="mfm").cycles_per_byte == 0.0


def test_a_sweep_with_no_window_has_no_width() -> None:
    assert Bracket(settings=()).width == 0.0


def test_a_stability_report_of_no_cell_has_no_spread() -> None:
    empty = StabilityReport(
        cell_ns=0.0, wow_flutter=0.0, drift=0.0, fastest_ns=0.0, slowest_ns=0.0, samples=0
    )

    assert empty.spread == 0.0


def test_a_series_shorter_than_its_window_is_left_alone() -> None:
    report = measure_stability(tuple(round(CELL * RATIOS[index % 3]) for index in range(9)))

    assert report.samples == 9


def test_a_drifting_drive_is_advised_about_slip() -> None:
    intervals = tuple(
        round(CELL * (1 + 0.05 * index / 6_000) * RATIOS[index % 3]) for index in range(6_000)
    )

    found = [item for item in advise(intervals).actions if item.subject == "belt and spindle"]

    assert found
    assert "slip" in found[0].action


def test_a_report_with_no_populated_cluster_has_no_spread() -> None:
    empty = IntervalReport(pulses=0, clusters=(), separations=(), outliers=0, rpm=None)

    assert empty.relative_spread == 0.0
    assert not empty.healthy


def test_a_scan_over_no_span_returns_its_only_candidate() -> None:
    base, _ = scan_bases((100, 150, 200), 100.0, 100.0, 4, RATIOS)

    assert base == 100.0


def test_refining_a_stream_of_nothing_keeps_the_base() -> None:
    assert refine_base((), 100.0, RATIOS) == 100.0


def test_refining_a_settled_base_holds_it() -> None:
    sample = tuple(round(CELL * ratio) for ratio in RATIOS for _ in range(50))
    settled = refine_base(sample, CELL, RATIOS)

    assert refine_base(sample, settled, RATIOS) == pytest.approx(settled, rel=1e-9)


def test_a_capture_whose_tracks_are_all_blank_still_reports(tmp_path: Path) -> None:
    noise = tuple(
        round(CELL * (0.5 + 1.5 * ((index * 7919) % 1000) / 1000)) for index in range(4000)
    )
    capture = FluxCapture(
        source=Source.FDSSTICK,
        tracks=(FluxTrack(index=0, revolutions=(Revolution(intervals=noise),)),),
    )
    path = tmp_path / "noise.raw"
    path.write_bytes(write_counts(capture))

    result = runner.invoke(app, ["flux", str(path)])

    assert "blank tracks" in result.stdout


def test_a_sweep_over_an_unreadable_capture_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "empty.raw"
    path.write_bytes(bytes(1))

    result = runner.invoke(app, ["tune-sweep", str(path)])

    assert result.exit_code == 1


def test_tuning_an_unreadable_capture_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "empty.raw"
    path.write_bytes(bytes(1))

    result = runner.invoke(app, ["tune", str(path)])

    assert result.exit_code == 1


def test_a_modulated_capture_still_analyses() -> None:
    intervals = tuple(
        round(CELL * (1 + 0.02 * math.sin(index / 50.0)) * RATIOS[index % 3])
        for index in range(3_000)
    )

    assert analyse_intervals(intervals).coherent


def test_an_incoherent_report_is_never_healthy() -> None:
    noisy = IntervalReport(
        pulses=100,
        clusters=(Cluster(label=0, centre_ns=1000.0, spread_ns=900.0, count=100),),
        separations=(),
        outliers=0,
        rpm=None,
    )

    assert not noisy.coherent
    assert not noisy.healthy


def test_refining_noisy_data_still_lands_near_the_cell() -> None:
    sample = tuple(
        round(CELL * RATIOS[index % 3] * (1 + 0.2 * (((index * 7919) % 97) / 97 - 0.5)))
        for index in range(400)
    )

    assert refine_base(sample, CELL * 0.8, RATIOS) > 0
