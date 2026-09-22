from __future__ import annotations

import pytest

from fdstoolkit.archive.store import DumpRecord
from fdstoolkit.archive.trend import Direction, trend_of


def _record(taken: str, bad: int, *, confidence: float = 0.95) -> DumpRecord:
    return DumpRecord(
        disk_id="disk-a",
        taken=taken,
        digest="d",
        grade="clean",
        confidence=confidence,
        blocks_total=100,
        blocks_bad=bad,
        drive="AN-500B",
    )


def test_a_disk_read_the_same_way_twice_is_stable() -> None:
    trend = trend_of([_record("2024-01-01", 2), _record("2026-01-01", 2)])

    assert trend.direction is Direction.STABLE
    assert trend.blocks_per_year == pytest.approx(0.0)


def test_a_disk_losing_blocks_is_degrading() -> None:
    trend = trend_of([_record("2024-01-01", 0), _record("2026-01-01", 20)])

    assert trend.direction is Direction.DEGRADING
    assert trend.blocks_per_year == pytest.approx(10.0, rel=0.02)


def test_a_disk_reading_better_than_before_is_improving() -> None:
    trend = trend_of([_record("2024-01-01", 20), _record("2026-01-01", 0)])

    assert trend.direction is Direction.IMPROVING
    assert trend.blocks_per_year < 0


def test_a_single_dump_says_nothing_about_direction() -> None:
    trend = trend_of([_record("2026-01-01", 5)])

    assert trend.direction is Direction.UNKNOWN
    assert trend.blocks_per_year == 0.0


def test_a_history_with_no_dump_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one dump"):
        trend_of([])


def test_two_dumps_on_the_same_day_cannot_give_a_rate() -> None:
    trend = trend_of([_record("2026-01-01", 0), _record("2026-01-01", 5)])

    assert trend.direction is Direction.UNKNOWN


def test_the_trend_carries_one_point_per_dump() -> None:
    trend = trend_of([_record("2024-01-01", 0), _record("2026-01-01", 20)])

    assert len(trend.points) == 2
    assert trend.points[0].bad_share == 0.0
    assert trend.points[1].bad_share == 0.2


def test_the_trend_reports_the_span_it_covers() -> None:
    trend = trend_of([_record("2024-01-01", 0), _record("2026-01-01", 20)])

    assert trend.years == pytest.approx(2.0, rel=0.01)


def test_the_trend_projects_when_the_disk_runs_out() -> None:
    trend = trend_of([_record("2024-01-01", 0), _record("2026-01-01", 20)])

    assert trend.years_remaining is not None
    assert trend.years_remaining == pytest.approx(8.0, rel=0.05)


def test_a_stable_disk_has_no_projection() -> None:
    trend = trend_of([_record("2024-01-01", 2), _record("2026-01-01", 2)])

    assert trend.years_remaining is None


def test_the_trend_renders_a_line_naming_its_direction() -> None:
    trend = trend_of([_record("2024-01-01", 0), _record("2026-01-01", 20)])

    assert "degrading" in trend.render()


def test_a_malformed_date_is_refused() -> None:
    with pytest.raises(ValueError, match="not a date"):
        trend_of([_record("whenever", 0), _record("2026-01-01", 1)])


def test_a_disk_already_past_its_blocks_has_no_time_left() -> None:
    trend = trend_of([_record("2024-01-01", 0), _record("2026-01-01", 120)])

    assert trend.years_remaining == 0.0
    assert "unreadable in about 0 years" in trend.render()
