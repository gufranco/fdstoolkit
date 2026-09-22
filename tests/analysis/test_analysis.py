from __future__ import annotations

import pytest

from fdstoolkit.flux.analysis import (
    HEALTHY_MARGIN,
    IntervalReport,
    analyse_capture,
    analyse_intervals,
    estimate_base_ns,
    histogram,
)
from fdstoolkit.flux.model import (
    LONG_NS,
    MEDIUM_NS,
    SHORT_NS,
    FluxCapture,
    FluxTrack,
    Revolution,
    Source,
)
from fdstoolkit.flux.synth import intervals_from_classes

CLEAN = bytes((0, 1, 2)) * 400


def test_a_histogram_counts_intervals_into_fixed_buckets() -> None:
    counts = histogram((1_000, 1_100, 9_000), bucket_ns=1_000)

    assert counts[1] == 2
    assert counts[9] == 1


def test_a_histogram_of_nothing_is_empty() -> None:
    assert histogram((), bucket_ns=1_000) == {}


def test_a_bucket_size_of_zero_is_refused() -> None:
    with pytest.raises(ValueError, match="bucket must be positive"):
        histogram((1,), bucket_ns=0)


def test_a_clean_stream_resolves_into_three_tight_clusters() -> None:
    report = analyse_intervals(intervals_from_classes(CLEAN))

    assert len(report.clusters) == 3
    assert [round(cluster.centre_ns) for cluster in report.clusters] == [
        SHORT_NS,
        MEDIUM_NS,
        LONG_NS,
    ]
    assert all(cluster.spread_ns == 0.0 for cluster in report.clusters)


def test_a_clean_stream_separates_perfectly() -> None:
    report = analyse_intervals(intervals_from_classes(CLEAN))

    assert report.worst_margin == pytest.approx(1.0)
    assert report.healthy
    assert report.outliers == 0


def test_jitter_narrows_the_margin_without_breaking_the_clusters() -> None:
    report = analyse_intervals(intervals_from_classes(CLEAN, jitter_ns=1_200, seed=3))

    assert len(report.clusters) == 3
    assert 0.0 < report.worst_margin < 1.0
    assert all(cluster.spread_ns > 0.0 for cluster in report.clusters)


def test_heavy_jitter_reports_an_unhealthy_stream() -> None:
    report = analyse_intervals(intervals_from_classes(CLEAN, jitter_ns=2_600, seed=5))

    assert report.worst_margin < HEALTHY_MARGIN
    assert not report.healthy


def test_an_interval_far_from_every_cluster_is_an_outlier() -> None:
    report = analyse_intervals((*intervals_from_classes(CLEAN), 400_000))

    assert report.outliers == 1


def test_a_stream_with_no_interval_is_refused() -> None:
    with pytest.raises(ValueError, match="no interval"):
        analyse_intervals(())


def test_speed_comes_from_the_revolution_when_one_is_given() -> None:
    report = analyse_intervals(intervals_from_classes(CLEAN), revolution_ns=625_000_000)

    assert report.rpm == pytest.approx(96.0, abs=0.01)


def test_speed_is_absent_when_no_revolution_is_given() -> None:
    report = analyse_intervals(intervals_from_classes(CLEAN))

    assert report.rpm is None


def test_a_capture_is_analysed_track_by_track() -> None:
    capture = FluxCapture(
        source=Source.SYNTHETIC,
        tracks=(
            FluxTrack(index=0, revolutions=(Revolution(intervals=intervals_from_classes(CLEAN)),)),
            FluxTrack(index=1, revolutions=(Revolution(intervals=intervals_from_classes(CLEAN)),)),
        ),
    )

    report = analyse_capture(capture)

    assert len(report.tracks) == 2
    assert report.healthy
    assert report.worst_margin == pytest.approx(1.0)
    assert report.tracks[1].index == 1


def test_a_capture_report_names_its_worst_track() -> None:
    capture = FluxCapture(
        source=Source.SYNTHETIC,
        tracks=(
            FluxTrack(index=0, revolutions=(Revolution(intervals=intervals_from_classes(CLEAN)),)),
            FluxTrack(
                index=1,
                revolutions=(
                    Revolution(
                        intervals=intervals_from_classes(CLEAN, jitter_ns=2_400, seed=11),
                    ),
                ),
            ),
        ),
    )

    report = analyse_capture(capture)

    assert report.worst_track == 1
    assert not report.healthy


def test_the_base_cell_is_measured_from_a_clean_stream() -> None:

    assert estimate_base_ns(intervals_from_classes(CLEAN)) == pytest.approx(SHORT_NS, rel=0.02)


def test_the_base_cell_follows_a_stream_recorded_at_another_speed() -> None:

    stretched = tuple(round(value * 1.45) for value in intervals_from_classes(CLEAN))

    assert estimate_base_ns(stretched) == pytest.approx(SHORT_NS * 1.45, rel=0.03)


def test_measuring_a_stream_with_no_interval_is_refused() -> None:

    with pytest.raises(ValueError, match="no interval"):
        estimate_base_ns(())


def test_a_report_converts_its_base_cell_into_a_bit_rate() -> None:
    report = analyse_intervals(intervals_from_classes(CLEAN))

    assert report.bit_rate_hz == pytest.approx(96_154, rel=0.02)


def test_a_report_without_a_base_cell_has_no_bit_rate() -> None:

    empty = IntervalReport(pulses=0, clusters=(), separations=(), outliers=0, rpm=None)

    assert empty.bit_rate_hz == 0.0
