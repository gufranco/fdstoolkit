from __future__ import annotations

import pytest

from fdstoolkit.flux.model import (
    NS_PER_SECOND,
    FluxCapture,
    FluxTrack,
    Revolution,
    Source,
    flag_partial,
)


def test_a_revolution_reports_its_pulse_count_and_duration() -> None:
    revolution = Revolution(intervals=(10_000, 15_000, 20_000))

    assert revolution.pulse_count == 3
    assert revolution.duration_ns == 45_000


def test_a_revolution_converts_its_duration_to_rpm() -> None:
    revolution = Revolution(intervals=(NS_PER_SECOND * 60 // 96,))

    assert revolution.rpm == pytest.approx(96.0, abs=0.01)


def test_an_empty_revolution_has_no_speed() -> None:
    revolution = Revolution(intervals=())

    assert revolution.rpm == 0.0


def test_a_track_without_a_revolution_is_refused() -> None:
    with pytest.raises(ValueError, match="carries no revolution"):
        FluxTrack(index=0, revolutions=())


def test_a_track_exposes_one_revolution_by_index() -> None:
    track = FluxTrack(
        index=2,
        revolutions=(Revolution(intervals=(1, 2)), Revolution(intervals=(3,))),
    )

    assert track.revolution_count == 2
    assert track.intervals(1) == (3,)
    assert track.all_intervals == (1, 2, 3)


def test_asking_a_track_for_a_missing_revolution_is_refused() -> None:
    track = FluxTrack(index=0, revolutions=(Revolution(intervals=(1,)),))

    with pytest.raises(ValueError, match="no revolution 4"):
        track.intervals(4)


def test_a_capture_without_a_track_is_refused() -> None:
    with pytest.raises(ValueError, match="carries no track"):
        FluxCapture(source=Source.SYNTHETIC, tracks=())


def test_a_capture_finds_a_track_by_its_own_index() -> None:
    capture = FluxCapture(
        source=Source.SCP,
        tracks=(FluxTrack(index=7, revolutions=(Revolution(intervals=(1, 2)),)),),
    )

    assert capture.track_count == 1
    assert capture.track(7).index == 7
    assert capture.pulse_count == 2


def test_asking_a_capture_for_a_missing_track_is_refused() -> None:
    capture = FluxCapture(
        source=Source.SCP,
        tracks=(FluxTrack(index=0, revolutions=(Revolution(intervals=(1,)),)),),
    )

    with pytest.raises(ValueError, match="no track 3"):
        capture.track(3)


def test_a_revolution_far_shorter_than_its_neighbours_is_partial() -> None:
    whole = Revolution(intervals=(1_000,) * 100)
    short = Revolution(intervals=(1_000,) * 50)

    flagged = flag_partial((whole, whole, whole, short))

    assert [item.complete for item in flagged] == [True, True, True, False]


def test_a_revolution_barely_shorter_stays_whole() -> None:
    whole = Revolution(intervals=(1_000,) * 100)
    nearly = Revolution(intervals=(1_000,) * 96)

    assert all(item.complete for item in flag_partial((whole, whole, whole, nearly)))


def test_too_few_revolutions_to_compare_are_left_alone() -> None:
    pair = (Revolution(intervals=(1_000,) * 100), Revolution(intervals=(1_000,)))

    assert all(item.complete for item in flag_partial(pair))


def test_revolutions_of_no_duration_are_left_alone() -> None:
    empty = (Revolution(intervals=()),) * 3

    assert all(item.complete for item in flag_partial(empty))
