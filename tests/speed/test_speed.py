from __future__ import annotations

import pytest

from fdstoolkit.drive.spec import NOMINAL_BIT_RATE_HZ
from fdstoolkit.drive.speed import Direction, Verdict, from_cycles


def test_a_console_reading_of_one_hundred_and_forty_eight_is_barely_fast() -> None:
    report = from_cycles(148)

    assert report.bit_rate_hz == pytest.approx(96_741, rel=0.001)
    assert report.error == pytest.approx(0.0036, abs=0.0005)
    assert report.verdict is Verdict.FINE
    assert report.direction is Direction.HOLD


def test_a_console_reading_of_one_hundred_and_forty_nine_is_barely_slow() -> None:
    report = from_cycles(149)

    assert report.error == pytest.approx(-0.0032, abs=0.0005)
    assert report.verdict is Verdict.FINE


def test_more_cycles_between_bytes_means_a_slower_disk() -> None:
    assert from_cycles(152).bit_rate_hz < from_cycles(148).bit_rate_hz
    assert from_cycles(152).direction is Direction.FASTER


def test_fewer_cycles_between_bytes_means_a_faster_disk() -> None:
    assert from_cycles(144).direction is Direction.SLOWER


def test_a_reading_inside_the_adapter_band_but_off_centre_is_only_in_spec() -> None:
    report = from_cycles(141)

    assert report.verdict is Verdict.IN_SPEC
    assert report.bit_rate_hz > NOMINAL_BIT_RATE_HZ


def test_a_reading_outside_the_adapter_band_is_out_of_spec() -> None:
    assert from_cycles(120).verdict is Verdict.OUT_OF_SPEC


def test_a_slow_drive_is_told_to_raise_the_motor_speed() -> None:
    report = from_cycles(152)

    assert "raise the motor speed" in report.advice
    assert "clockwise" not in report.advice


def test_a_fast_drive_is_told_to_lower_the_motor_speed() -> None:
    report = from_cycles(144)

    assert "lower the motor speed" in report.advice
    assert "clockwise" not in report.advice


def test_a_finely_set_drive_is_told_to_leave_the_speed_alone() -> None:
    assert "leave the motor speed alone" in from_cycles(148).advice


def test_the_report_renders_the_rate_the_verdict_and_the_advice() -> None:
    text = from_cycles(152).render()

    assert "kbit/s" in text
    assert "%" in text
    assert "raise the motor speed" in text


def test_a_reading_of_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="positive"):
        from_cycles(0)
