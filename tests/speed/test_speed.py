from __future__ import annotations

import pytest

from fdstoolkit.drive.spec import NOMINAL_BIT_RATE_HZ, cell_from_bit_rate
from fdstoolkit.drive.speed import Direction, Verdict, from_cycles, measure_speed

NOMINAL_CELL = cell_from_bit_rate(NOMINAL_BIT_RATE_HZ)


def _at(bit_rate: float, pulses: int = 3_000) -> tuple[int, ...]:
    cell = cell_from_bit_rate(bit_rate)
    return tuple(round(cell * ratio) for ratio in (1.0, 1.5, 2.0) for _ in range(pulses))


def test_a_drive_at_the_nominal_rate_is_finely_set() -> None:
    report = measure_speed(_at(NOMINAL_BIT_RATE_HZ))

    assert report.verdict is Verdict.FINE
    assert report.bit_rate_hz == pytest.approx(NOMINAL_BIT_RATE_HZ, rel=0.002)
    assert report.direction is Direction.HOLD


def test_a_drive_inside_the_adapter_band_but_off_centre_is_only_in_spec() -> None:
    report = measure_speed(_at(NOMINAL_BIT_RATE_HZ * 1.05))

    assert report.verdict is Verdict.IN_SPEC
    assert report.direction is Direction.SLOWER


def test_a_drive_running_slow_inside_the_band_is_told_to_speed_up() -> None:
    report = measure_speed(_at(NOMINAL_BIT_RATE_HZ * 0.95))

    assert report.verdict is Verdict.IN_SPEC
    assert report.direction is Direction.FASTER


def test_a_drive_outside_the_adapter_band_is_out_of_spec() -> None:
    report = measure_speed(_at(NOMINAL_BIT_RATE_HZ * 1.2))

    assert report.verdict is Verdict.OUT_OF_SPEC
    assert report.direction is Direction.SLOWER


def test_the_error_is_reported_as_a_share_of_nominal() -> None:
    report = measure_speed(_at(NOMINAL_BIT_RATE_HZ * 1.05))

    assert report.error == pytest.approx(0.05, abs=0.005)


def test_a_finely_set_drive_has_almost_no_headroom_left() -> None:
    report = measure_speed(_at(NOMINAL_BIT_RATE_HZ))

    assert report.headroom > 0.9


def test_a_drive_at_the_edge_of_the_band_has_no_headroom() -> None:
    report = measure_speed(_at(NOMINAL_BIT_RATE_HZ * 1.1))

    assert report.headroom == pytest.approx(0.0, abs=0.05)


def test_the_report_carries_the_cell_and_the_capture_counts() -> None:
    report = measure_speed(_at(NOMINAL_BIT_RATE_HZ))

    assert report.cell_ns == pytest.approx(NOMINAL_CELL, rel=0.002)
    assert report.counts == pytest.approx(62, abs=0.5)


def test_the_report_carries_the_console_side_cycle_count() -> None:
    report = measure_speed(_at(NOMINAL_BIT_RATE_HZ))

    assert report.cycles_per_byte == pytest.approx(148.5, abs=1.0)


def test_a_capture_with_no_pulse_is_refused() -> None:
    with pytest.raises(ValueError, match="no interval"):
        measure_speed(())


def test_the_report_renders_a_line_naming_what_to_do() -> None:
    text = measure_speed(_at(NOMINAL_BIT_RATE_HZ * 0.95)).render()

    assert "faster" in text
    assert "%" in text


def test_a_finely_set_drive_renders_as_settled() -> None:
    assert "hold" in measure_speed(_at(NOMINAL_BIT_RATE_HZ)).render()


def test_a_console_reading_of_one_hundred_and_forty_eight_is_barely_fast() -> None:
    report = from_cycles(148)

    assert report.bit_rate_hz == pytest.approx(96_741, rel=0.001)
    assert report.error == pytest.approx(0.0036, abs=0.0005)
    assert report.verdict is Verdict.FINE


def test_a_console_reading_of_one_hundred_and_forty_nine_is_barely_slow() -> None:
    report = from_cycles(149)

    assert report.error == pytest.approx(-0.0032, abs=0.0005)
    assert report.verdict is Verdict.FINE


def test_more_cycles_between_bytes_means_a_slower_disk() -> None:
    assert from_cycles(152).bit_rate_hz < from_cycles(148).bit_rate_hz
    assert from_cycles(152).direction is Direction.FASTER


def test_fewer_cycles_between_bytes_means_a_faster_disk() -> None:
    assert from_cycles(144).direction is Direction.SLOWER


def test_a_console_reading_round_trips_through_the_cycle_count() -> None:
    assert from_cycles(148).cycles_per_byte == pytest.approx(148, rel=1e-9)


def test_a_reading_of_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="positive"):
        from_cycles(0)
