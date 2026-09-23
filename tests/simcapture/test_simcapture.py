from __future__ import annotations

import pytest

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.drive.spec import NOMINAL_BIT_RATE_HZ
from fdstoolkit.drive.speed import Verdict, measure_speed
from fdstoolkit.flux.counts import read_counts
from fdstoolkit.hardware.simulation import CaptureMode, SimulatedDrive


def _disk() -> Disk:
    payload = bytes([BlockKind.DISK_INFO]) + b"*NINTENDO-HVC*" + bytes(41)
    return Disk(
        sides=(
            Side(
                blocks=(Block(kind=BlockKind.DISK_INFO, payload=payload),),
                tail=b"",
                capacity=65500,
            ),
        )
    )


def _drain(drive: SimulatedDrive, side: int = 0) -> None:
    list(drive.read_side(side))


def test_a_drive_keeps_no_capture_before_it_reads() -> None:
    assert SimulatedDrive(_disk()).captures == ()


def test_reading_a_side_keeps_a_capture() -> None:
    drive = SimulatedDrive(_disk())

    _drain(drive)

    assert len(drive.captures) == 1
    assert drive.captures[0]


def test_reading_twice_keeps_two_captures() -> None:
    drive = SimulatedDrive(_disk())

    _drain(drive)
    _drain(drive)

    assert len(drive.captures) == 2


def test_the_default_capture_carries_pulse_classes() -> None:
    drive = SimulatedDrive(_disk())

    _drain(drive)

    assert drive.capture_mode is CaptureMode.CLASSES
    assert all(value <= 3 for value in drive.captures[0][:64])


def test_a_timing_drive_carries_interval_counts() -> None:
    drive = SimulatedDrive(_disk(), capture_mode=CaptureMode.TIMING)

    _drain(drive)

    counts = drive.captures[0]
    assert max(counts) > 3


def test_a_timing_capture_measures_the_nominal_rate() -> None:
    drive = SimulatedDrive(_disk(), capture_mode=CaptureMode.TIMING)

    _drain(drive)

    report = measure_speed(read_counts(drive.captures[0]).track(0).intervals())
    assert report.bit_rate_hz == pytest.approx(NOMINAL_BIT_RATE_HZ, rel=0.02)
    assert report.verdict is Verdict.FINE


def test_a_drive_can_stand_in_for_one_running_slow() -> None:
    drive = SimulatedDrive(
        _disk(),
        capture_mode=CaptureMode.TIMING,
        bit_rate_hz=NOMINAL_BIT_RATE_HZ * 0.88,
    )

    _drain(drive)

    report = measure_speed(read_counts(drive.captures[0]).track(0).intervals())
    assert report.verdict is Verdict.OUT_OF_SPEC
    assert report.error < 0


def test_a_drive_can_stand_in_for_one_running_fast() -> None:
    drive = SimulatedDrive(
        _disk(),
        capture_mode=CaptureMode.TIMING,
        bit_rate_hz=NOMINAL_BIT_RATE_HZ * 1.12,
    )

    _drain(drive)

    assert measure_speed(read_counts(drive.captures[0]).track(0).intervals()).error > 0


def test_a_rate_of_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="positive"):
        SimulatedDrive(_disk(), capture_mode=CaptureMode.TIMING, bit_rate_hz=0)


def test_a_drive_with_no_disk_keeps_no_capture() -> None:
    drive = SimulatedDrive(None)

    with pytest.raises(Exception, match="no disk"):
        _drain(drive)

    assert drive.captures == ()
