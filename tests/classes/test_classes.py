from __future__ import annotations

import pytest

from fdstoolkit.codecs.raw import pack_raw03
from fdstoolkit.drive.classes import (
    HEALTHY_SHARES,
    ClassReport,
    Reading,
    measure_classes,
)


def _values(short: int, medium: int, long_: int, invalid: int = 0) -> bytes:
    return bytes([0] * short + [1] * medium + [2] * long_ + [3] * invalid)


def _healthy(total: int = 10_000) -> bytes:
    return _values(
        round(total * HEALTHY_SHARES[0]),
        round(total * HEALTHY_SHARES[1]),
        round(total * HEALTHY_SHARES[2]),
    )


def test_a_healthy_spread_reads_as_healthy() -> None:
    report = measure_classes(_healthy())

    assert report.reading is Reading.HEALTHY
    assert report.glitch_rate == 0.0


def test_the_shares_are_reported_for_every_class() -> None:
    report = measure_classes(_healthy())

    assert report.shares[0] == pytest.approx(HEALTHY_SHARES[0], abs=0.01)
    assert sum(report.shares) == pytest.approx(1.0)


def test_a_single_glitch_is_counted() -> None:
    report = measure_classes(_values(740, 190, 69, 1))

    assert report.glitches == 1
    assert report.glitch_rate == pytest.approx(0.001)


def test_glitches_above_the_floor_read_as_glitching() -> None:
    report = measure_classes(_values(700, 190, 60, 50))

    assert report.reading is Reading.GLITCHING


def test_a_spread_shifted_towards_long_pulses_reads_as_slow() -> None:
    report = measure_classes(_values(400, 300, 300))

    assert report.reading is Reading.SHIFTED
    assert report.drift > 0


def test_a_spread_shifted_towards_short_pulses_reads_as_fast() -> None:
    report = measure_classes(_values(950, 40, 10))

    assert report.reading is Reading.SHIFTED
    assert report.drift < 0


def test_a_glitching_read_outranks_a_shifted_one() -> None:
    report = measure_classes(_values(400, 300, 250, 50))

    assert report.reading is Reading.GLITCHING


def test_the_drift_of_a_healthy_spread_is_near_zero() -> None:
    assert abs(measure_classes(_healthy()).drift) < 0.05


def test_packed_values_are_accepted() -> None:
    report = measure_classes(pack_raw03(_healthy()), packed=True)

    assert report.reading is Reading.HEALTHY


def test_a_stream_with_no_value_is_refused() -> None:
    with pytest.raises(ValueError, match="no pulse"):
        measure_classes(b"")


def test_the_report_renders_the_shares_and_the_verdict() -> None:
    text = measure_classes(_healthy()).render()

    assert "short" in text
    assert "healthy" in text


def test_a_glitching_report_names_the_glitches() -> None:
    text = measure_classes(_values(700, 190, 60, 50)).render()

    assert "glitch" in text


def test_a_shifted_report_says_which_way() -> None:
    assert "slow" in measure_classes(_values(400, 300, 300)).render()
    assert "fast" in measure_classes(_values(950, 40, 10)).render()


def test_the_reference_shares_come_from_the_protocol_document() -> None:
    assert HEALTHY_SHARES == (0.74, 0.19, 0.07)


def test_a_report_of_no_pulse_has_no_shares_and_no_drift() -> None:
    empty = ClassReport(counts=(0, 0, 0, 0))

    assert empty.shares == (0.0, 0.0, 0.0, 0.0)
    assert empty.drift == 0.0


def test_a_report_of_glitches_alone_has_no_drift() -> None:
    assert ClassReport(counts=(0, 0, 0, 5)).drift == 0.0
