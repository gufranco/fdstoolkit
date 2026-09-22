from __future__ import annotations

import pytest

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.flux.model import LONG_NS, MEDIUM_NS, SHORT_NS, Source
from fdstoolkit.flux.synth import intervals_from_classes, synthesise


def _side() -> Side:
    payload = bytes([BlockKind.DISK_INFO]) + b"*NINTENDO-HVC*" + bytes(41)
    return Side(
        blocks=(Block(kind=BlockKind.DISK_INFO, payload=payload),),
        tail=b"",
        capacity=65500,
    )


def test_pulse_classes_map_onto_nominal_intervals() -> None:
    result = intervals_from_classes(bytes((0, 1, 2)))

    assert result == (SHORT_NS, MEDIUM_NS, LONG_NS)


def test_an_out_of_range_class_is_refused() -> None:
    with pytest.raises(ValueError, match="between 0 and 2"):
        intervals_from_classes(bytes((3,)))


def test_jitter_moves_an_interval_without_changing_its_count() -> None:
    clean = intervals_from_classes(bytes((0, 1, 2)) * 20)
    noisy = intervals_from_classes(bytes((0, 1, 2)) * 20, jitter_ns=400, seed=7)

    assert len(noisy) == len(clean)
    assert noisy != clean
    assert all(abs(a - b) <= 400 for a, b in zip(clean, noisy, strict=True))


def test_the_same_seed_produces_the_same_jitter() -> None:
    first = intervals_from_classes(bytes((0, 1, 2)) * 10, jitter_ns=300, seed=1)
    second = intervals_from_classes(bytes((0, 1, 2)) * 10, jitter_ns=300, seed=1)

    assert first == second


def test_a_synthesised_capture_carries_one_track_per_side() -> None:
    disk = Disk(sides=(_side(), _side()))

    capture = synthesise(disk)

    assert capture.source is Source.SYNTHETIC
    assert capture.track_count == 2
    assert capture.track(0).revolution_count == 1
    assert capture.pulse_count > 0


def test_a_synthesised_capture_can_hold_several_revolutions() -> None:
    disk = Disk(sides=(_side(),))

    capture = synthesise(disk, revolutions=3)

    assert capture.track(0).revolution_count == 3


def test_asking_for_no_revolution_is_refused() -> None:
    disk = Disk(sides=(_side(),))

    with pytest.raises(ValueError, match="at least one revolution"):
        synthesise(disk, revolutions=0)
