from __future__ import annotations

import pytest

from fdstoolkit.drive.spec import (
    ACCEPT_TOLERANCE,
    CAPTURE_CLOCK_HZ,
    FINE_TOLERANCE,
    HEAD_GAP_MM,
    HEAD_GAP_TOLERANCE_MM,
    HEAD_TURN_MM,
    NOMINAL_BIT_RATE_HZ,
    Band,
    accept_band,
    bit_rate_from_cell,
    cell_from_bit_rate,
    counts_from_cell,
    fine_band,
    head_turns_for,
)


def test_the_nominal_bit_rate_is_the_rate_the_adapter_expects() -> None:
    assert NOMINAL_BIT_RATE_HZ == 96_400


def test_the_nominal_cell_is_the_reciprocal_of_the_bit_rate() -> None:
    assert cell_from_bit_rate(NOMINAL_BIT_RATE_HZ) == pytest.approx(10_373, rel=1e-3)


def test_a_cell_converts_back_into_a_bit_rate() -> None:
    cell = cell_from_bit_rate(NOMINAL_BIT_RATE_HZ)

    assert bit_rate_from_cell(cell) == pytest.approx(NOMINAL_BIT_RATE_HZ, rel=1e-6)


def test_a_cell_of_no_length_has_no_bit_rate() -> None:
    assert bit_rate_from_cell(0) == 0.0


def test_the_nominal_cell_is_sixty_two_counts_on_the_capture_clock() -> None:
    assert counts_from_cell(cell_from_bit_rate(NOMINAL_BIT_RATE_HZ)) == pytest.approx(62, abs=0.5)
    assert CAPTURE_CLOCK_HZ == 6_000_000


def test_the_accept_band_is_the_ten_percent_the_adapter_tolerates() -> None:
    band = accept_band()

    assert band.low == pytest.approx(NOMINAL_BIT_RATE_HZ * (1 - ACCEPT_TOLERANCE))
    assert band.high == pytest.approx(NOMINAL_BIT_RATE_HZ * (1 + ACCEPT_TOLERANCE))


def test_the_fine_band_is_far_tighter_than_the_accept_band() -> None:
    assert FINE_TOLERANCE < ACCEPT_TOLERANCE
    assert fine_band().width < accept_band().width


def test_a_band_reports_whether_a_rate_sits_inside_it() -> None:
    band = accept_band()

    assert band.holds(NOMINAL_BIT_RATE_HZ)
    assert not band.holds(NOMINAL_BIT_RATE_HZ * 2)


def test_a_band_measures_how_far_off_centre_a_rate_sits() -> None:
    band = Band(low=90.0, high=110.0, centre=100.0)

    assert band.offset(100.0) == 0.0
    assert band.offset(110.0) == pytest.approx(1.0)
    assert band.offset(90.0) == pytest.approx(-1.0)


def test_a_band_of_no_width_reports_no_offset() -> None:
    assert Band(low=100.0, high=100.0, centre=100.0).offset(100.0) == 0.0


def test_the_head_gap_carries_its_published_tolerance() -> None:
    assert pytest.approx(10.72) == HEAD_GAP_MM
    assert pytest.approx(0.05) == HEAD_GAP_TOLERANCE_MM


def test_an_eighth_of_a_turn_moves_the_head_one_tolerance_width() -> None:
    assert pytest.approx(0.05) == HEAD_TURN_MM
    assert head_turns_for(0.05) == pytest.approx(0.125)
    assert head_turns_for(0.10) == pytest.approx(0.25)


def test_no_movement_needs_no_turn() -> None:
    assert head_turns_for(0.0) == 0.0
