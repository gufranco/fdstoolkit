from __future__ import annotations

import math

import pytest

from fdstoolkit.drive.spec import NOMINAL_BIT_RATE_HZ, cell_from_bit_rate
from fdstoolkit.drive.stability import Motion, cell_series, measure_stability

CELL = cell_from_bit_rate(NOMINAL_BIT_RATE_HZ)
RATIOS = (1.0, 1.5, 2.0)


def _steady(pulses: int = 6_000) -> tuple[int, ...]:
    return tuple(round(CELL * RATIOS[index % 3]) for index in range(pulses))


def _modulated(depth: float, period: int, pulses: int = 6_000) -> tuple[int, ...]:
    return tuple(
        round(CELL * (1 + depth * math.sin(2 * math.pi * index / period)) * RATIOS[index % 3])
        for index in range(pulses)
    )


def _drifting(total: float, pulses: int = 6_000) -> tuple[int, ...]:
    return tuple(
        round(CELL * (1 + total * index / pulses) * RATIOS[index % 3]) for index in range(pulses)
    )


def test_a_steady_capture_yields_a_flat_cell_series() -> None:
    series = cell_series(_steady(), base_ns=CELL, ratios=RATIOS)

    assert len(series) == 6_000
    assert max(series) - min(series) < CELL * 0.01


def test_a_series_needs_intervals() -> None:
    with pytest.raises(ValueError, match="no interval"):
        cell_series((), base_ns=CELL, ratios=RATIOS)


def test_a_steady_drive_measures_almost_no_wow() -> None:
    report = measure_stability(_steady())

    assert report.wow_flutter < 0.002
    assert report.motion is Motion.STEADY


def test_a_modulated_drive_shows_wow_and_is_named_periodic() -> None:
    report = measure_stability(_modulated(depth=0.03, period=900))

    assert report.wow_flutter > 0.01
    assert report.motion is Motion.PERIODIC


def test_a_drifting_drive_is_named_drifting() -> None:
    report = measure_stability(_drifting(total=0.06))

    assert report.motion is Motion.DRIFTING
    assert abs(report.drift) > 0.02


def test_drift_carries_its_direction() -> None:
    assert measure_stability(_drifting(total=0.06)).drift > 0
    assert measure_stability(_drifting(total=-0.06)).drift < 0


def test_a_steady_drive_has_almost_no_drift() -> None:
    assert abs(measure_stability(_steady()).drift) < 0.005


def test_the_report_carries_the_measured_cell_and_extremes() -> None:
    report = measure_stability(_steady())

    assert report.cell_ns == pytest.approx(CELL, rel=0.002)
    assert report.slowest_ns >= report.cell_ns >= report.fastest_ns


def test_a_capture_with_no_pulse_is_refused() -> None:
    with pytest.raises(ValueError, match="no interval"):
        measure_stability(())


def test_a_steady_drive_renders_as_steady() -> None:
    assert "steady" in measure_stability(_steady()).render()


def test_a_modulated_drive_renders_its_wow() -> None:
    text = measure_stability(_modulated(depth=0.03, period=900)).render()

    assert "wow" in text
    assert "%" in text


def test_a_tighter_drive_scores_better_than_a_looser_one() -> None:
    tight = measure_stability(_modulated(depth=0.004, period=900))
    loose = measure_stability(_modulated(depth=0.03, period=900))

    assert tight.quality > loose.quality
    assert 0.0 <= loose.quality <= 1.0
