from __future__ import annotations

import pytest

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.quality.calibrate import (
    Attribution,
    DriveVerdict,
    attribute,
    calibrate,
)


def _disk(tail: bytes = bytes(41)) -> Disk:
    payload = bytes([BlockKind.DISK_INFO]) + b"*NINTENDO-HVC*" + tail
    return Disk(
        sides=(
            Side(
                blocks=(Block(kind=BlockKind.DISK_INFO, payload=payload),),
                tail=b"",
                capacity=65500,
            ),
        )
    )


def _other() -> Disk:
    return _disk(bytes([0xAB]) + bytes(40))


def test_a_drive_that_reads_the_reference_back_exactly_is_good() -> None:
    profile = calibrate(_disk(), [_disk(), _disk(), _disk()])

    assert profile.passes == 3
    assert profile.blocks_wrong == 0
    assert profile.error_rate == 0.0
    assert profile.verdict is DriveVerdict.GOOD


def test_a_drive_that_misreads_sometimes_is_marginal() -> None:
    reads = [_disk()] * 99 + [_other()]

    profile = calibrate(_disk(), reads)

    assert profile.blocks_wrong == 1
    assert profile.error_rate == pytest.approx(0.01)
    assert profile.verdict is DriveVerdict.MARGINAL


def test_a_drive_that_misreads_often_is_faulty() -> None:
    reads = [_disk(), _other(), _other(), _other()]

    profile = calibrate(_disk(), reads)

    assert profile.verdict is DriveVerdict.FAULTY


def test_calibration_without_a_read_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one read"):
        calibrate(_disk(), [])


def test_a_read_of_another_shape_is_refused() -> None:
    two = Disk(sides=(_disk().sides[0], _disk().sides[0]))

    with pytest.raises(ValueError, match="different shape"):
        calibrate(_disk(), [two])


def test_an_error_rate_within_the_drive_noise_is_blamed_on_the_drive() -> None:
    profile = calibrate(_disk(), [_disk()] * 9 + [_other()])

    assert attribute(profile, observed_rate=0.08) is Attribution.DRIVE


def test_an_error_rate_far_above_the_drive_noise_is_blamed_on_the_disk() -> None:
    profile = calibrate(_disk(), [_disk()] * 999 + [_other()])

    assert attribute(profile, observed_rate=0.4) is Attribution.DISK


def test_an_error_rate_somewhat_above_the_noise_blames_both() -> None:
    profile = calibrate(_disk(), [_disk()] * 9 + [_other()])

    assert attribute(profile, observed_rate=0.25) is Attribution.BOTH


def test_a_clean_run_on_a_clean_drive_blames_nothing() -> None:
    profile = calibrate(_disk(), [_disk(), _disk()])

    assert attribute(profile, observed_rate=0.0) is Attribution.NEITHER
