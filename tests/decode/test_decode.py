from __future__ import annotations

import pytest

from fdstoolkit.codecs.fds import SIDE_SIZE
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.flux.decode import (
    BOUNDARIES,
    classes_from_intervals,
    decode_capture,
    decode_track,
    fitted_boundaries,
)
from fdstoolkit.flux.model import LONG_NS, MEDIUM_NS, SHORT_NS, FluxTrack, Revolution
from fdstoolkit.flux.synth import synthesise


def _disk(sides: int = 1) -> Disk:
    payload = bytes([BlockKind.DISK_INFO]) + b"*NINTENDO-HVC*" + bytes(41)
    side = Side(
        blocks=(Block(kind=BlockKind.DISK_INFO, payload=payload),),
        tail=b"",
        capacity=65500,
    )
    return Disk(sides=tuple(side for _ in range(sides)))


def test_intervals_quantise_back_into_pulse_classes() -> None:
    result = classes_from_intervals((SHORT_NS, MEDIUM_NS, LONG_NS))

    assert result == bytes((0, 1, 2))


def test_an_interval_between_two_classes_takes_the_nearer_one() -> None:
    result = classes_from_intervals((SHORT_NS + 400,))

    assert result == bytes((0,))


def test_a_very_long_interval_saturates_at_the_top_class() -> None:
    result = classes_from_intervals((LONG_NS * 4,))

    assert result == bytes((3,))


def test_quantising_nothing_gives_nothing() -> None:
    assert classes_from_intervals(()) == b""


def test_a_synthesised_track_decodes_back_to_its_block() -> None:
    disk = _disk()

    capture = synthesise(disk)
    side, findings = decode_track(capture.track(0))

    assert not [finding for finding in findings if finding.severity == "error"]
    assert side.blocks[0].payload == disk.sides[0].blocks[0].payload


def test_jitter_inside_the_margin_still_decodes() -> None:
    disk = _disk()

    capture = synthesise(disk, jitter_ns=1_500, seed=2)
    side, _ = decode_track(capture.track(0))

    assert side.blocks[0].payload == disk.sides[0].blocks[0].payload


def test_a_capture_decodes_every_track_into_a_disk() -> None:
    disk = _disk(sides=2)

    decoded, findings = decode_capture(synthesise(disk))

    assert decoded.side_count == 2
    assert not [finding for finding in findings if finding.severity == "error"]
    assert decoded.sides[1].blocks[0].payload == disk.sides[1].blocks[0].payload


def test_decoding_picks_the_revolution_that_reads_cleanest() -> None:
    disk = _disk()
    good = synthesise(disk).track(0).revolutions[0]
    ruined = Revolution(intervals=(SHORT_NS,) * 5_000)
    track = FluxTrack(index=0, revolutions=(ruined, good))

    side, _ = decode_track(track)

    assert side.blocks[0].payload == disk.sides[0].blocks[0].payload


def test_a_track_that_never_decodes_reports_the_failure() -> None:
    track = FluxTrack(index=0, revolutions=(Revolution(intervals=(SHORT_NS,) * 5_000),))

    side, findings = decode_track(track)

    assert not side.blocks
    assert any(finding.code == "FDS014" for finding in findings)


def test_a_capture_with_no_decodable_track_is_still_a_disk() -> None:
    track = FluxTrack(index=0, revolutions=(Revolution(intervals=(SHORT_NS,) * 5_000),))
    capture = synthesise(_disk())
    ruined = type(capture)(source=capture.source, tracks=(track,))

    decoded, findings = decode_capture(ruined)

    assert decoded.side_count == 1
    assert any(finding.code == "FDS014" for finding in findings)


def test_capture_findings_name_the_side_they_came_from() -> None:
    disk = _disk(sides=2)
    capture = synthesise(disk)
    bad = type(capture)(
        source=capture.source,
        tracks=(
            capture.track(0),
            FluxTrack(index=1, revolutions=(Revolution(intervals=(SHORT_NS,) * 5_000),)),
        ),
    )

    _, findings = decode_capture(bad)

    assert [finding.side for finding in findings if finding.code == "FDS014"] == [1]


def test_decoding_a_revolution_with_no_pulse_is_refused() -> None:
    track = FluxTrack(index=0, revolutions=(Revolution(intervals=()),))

    with pytest.raises(ValueError, match="no interval"):
        decode_track(track)


def test_fitted_boundaries_fall_back_on_a_short_stream() -> None:

    assert fitted_boundaries((SHORT_NS, MEDIUM_NS)) == BOUNDARIES


def test_fitted_boundaries_track_a_stream_recorded_at_another_speed() -> None:

    stretched = tuple(round(value * 1.45) for value in (SHORT_NS, MEDIUM_NS, LONG_NS) * 100)

    fitted = fitted_boundaries(stretched)

    assert fitted != BOUNDARIES
    assert fitted[0] > BOUNDARIES[0]


def test_a_stream_recorded_at_another_speed_still_decodes() -> None:
    disk = _disk()
    capture = synthesise(disk)
    stretched = FluxTrack(
        index=0,
        revolutions=(
            Revolution(
                intervals=tuple(round(v * 1.45) for v in capture.track(0).intervals()),
            ),
        ),
    )

    side, _ = decode_track(stretched)

    assert side.blocks[0].payload == disk.sides[0].blocks[0].payload


def test_a_fixed_threshold_run_can_be_asked_for() -> None:
    disk = _disk()
    capture = synthesise(disk)

    side, _ = decode_track(capture.track(0), adaptive=False)

    assert side.blocks[0].payload == disk.sides[0].blocks[0].payload


def test_a_capture_can_be_decoded_without_fitting() -> None:
    decoded, _ = decode_capture(synthesise(_disk()), adaptive=False)

    assert decoded.side_count == 1


def test_a_decoded_side_carries_the_standard_capacity() -> None:
    decoded, _ = decode_capture(synthesise(_disk()))

    assert decoded.sides[0].capacity == SIDE_SIZE
