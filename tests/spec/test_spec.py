from __future__ import annotations

import pytest

from fdstoolkit.drive.spec import (
    ACCEPT_TOLERANCE,
    FINE_TOLERANCE,
    NOMINAL_BIT_RATE_HZ,
    accept_band,
    bit_rate_from_cell,
    cell_from_bit_rate,
    fine_band,
)


def test_the_nominal_bit_rate_is_the_rate_the_adapter_expects() -> None:
    assert NOMINAL_BIT_RATE_HZ == 96_400


def test_the_nominal_cell_is_the_reciprocal_of_the_bit_rate() -> None:
    assert cell_from_bit_rate(NOMINAL_BIT_RATE_HZ) == pytest.approx(10_373, rel=1e-3)


def test_a_rate_of_nothing_has_no_cell() -> None:
    assert cell_from_bit_rate(0) == 0.0


def test_a_cell_converts_back_into_a_bit_rate() -> None:
    cell = cell_from_bit_rate(NOMINAL_BIT_RATE_HZ)

    assert bit_rate_from_cell(cell) == pytest.approx(NOMINAL_BIT_RATE_HZ, rel=1e-6)


def test_a_cell_of_no_length_has_no_bit_rate() -> None:
    assert bit_rate_from_cell(0) == 0.0


def test_the_accept_band_is_the_ten_percent_the_adapter_tolerates() -> None:
    band = accept_band()

    assert band.low == pytest.approx(NOMINAL_BIT_RATE_HZ * (1 - ACCEPT_TOLERANCE))
    assert band.high == pytest.approx(NOMINAL_BIT_RATE_HZ * (1 + ACCEPT_TOLERANCE))


def test_the_fine_band_is_far_tighter_than_the_accept_band() -> None:
    fine = fine_band()
    accept = accept_band()

    assert FINE_TOLERANCE < ACCEPT_TOLERANCE
    assert accept.low < fine.low < fine.high < accept.high


def test_a_band_reports_whether_a_rate_sits_inside_it() -> None:
    band = accept_band()

    assert band.holds(NOMINAL_BIT_RATE_HZ)
    assert not band.holds(NOMINAL_BIT_RATE_HZ * 2)
