from __future__ import annotations

import pytest

from fdstoolkit.codecs.raw import pack_raw03
from fdstoolkit.flux.counts import (
    CAPTURE_CLOCK_HZ,
    TICK_NS,
    counts_to_ns,
    read_counts,
    read_raw03,
    write_counts,
)
from fdstoolkit.flux.model import LONG_NS, MEDIUM_NS, SHORT_NS, Source


def test_a_tick_is_the_period_of_the_capture_clock() -> None:
    assert pytest.approx(1_000_000_000 / CAPTURE_CLOCK_HZ) == TICK_NS


def test_a_count_converts_to_nanoseconds() -> None:
    assert counts_to_ns(60) == round(60 * TICK_NS)


def test_counts_become_one_track_of_intervals() -> None:
    capture = read_counts(bytes((60, 90, 120)))

    assert capture.source is Source.FDSSTICK
    assert capture.track(0).intervals() == (
        counts_to_ns(60),
        counts_to_ns(90),
        counts_to_ns(120),
    )


def test_a_capture_with_no_count_is_refused() -> None:
    with pytest.raises(ValueError, match="no pulse"):
        read_counts(b"")


def test_counts_round_trip_through_the_writer() -> None:
    capture = read_counts(bytes((60, 90, 120)))

    assert write_counts(capture) == bytes((60, 90, 120))


def test_a_count_beyond_one_byte_saturates_on_write() -> None:
    capture = read_counts(bytes((60,)))
    stretched = type(capture)(
        source=capture.source,
        tracks=(
            type(capture.tracks[0])(
                index=0,
                revolutions=(type(capture.tracks[0].revolutions[0])(intervals=(10_000_000,)),),
            ),
        ),
    )

    assert write_counts(stretched) == bytes((255,))


def test_packed_pulse_classes_become_nominal_intervals() -> None:
    capture = read_raw03(pack_raw03(bytes((0, 1, 2, 0))))

    assert capture.track(0).intervals() == (SHORT_NS, MEDIUM_NS, LONG_NS, SHORT_NS)


def test_a_packed_stream_with_no_value_is_refused() -> None:
    with pytest.raises(ValueError, match="no pulse"):
        read_raw03(b"")


def test_the_track_index_can_be_named() -> None:
    assert read_counts(bytes((60,)), track=5).track(5).index == 5
    assert read_raw03(pack_raw03(bytes((0,))), track=4).track(4).index == 4
