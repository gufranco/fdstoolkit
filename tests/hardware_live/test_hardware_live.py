from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from fdstoolkit.build.calibration import calibration_disk
from fdstoolkit.drive.monitor import Mode, calibrate
from fdstoolkit.hardware.fdsstick import FdsStick, open_fdsstick
from fdstoolkit.hardware.session import Grade, dump, write_verified
from fdstoolkit.quality.surface import SurfacePlan, surface_test

pytestmark = pytest.mark.hardware

DRIVE_ENV = "FDSTOOLKIT_HARDWARE"
SCRATCH_ENV = "FDSTOOLKIT_SCRATCH_DISK"
ONE_SIDE = 1
CALIBRATION_READS = 3


def required(name: str, reason: str) -> None:
    if os.environ.get(name) != "1":
        pytest.skip(f"set {name}=1 {reason}")


@pytest.fixture(name="stick")
def stick_fixture() -> Iterator[FdsStick]:
    required(DRIVE_ENV, "with an FDSStick attached and a factory disk in the drive to run this")
    stick = open_fdsstick()
    yield stick
    stick.close()


def test_two_dumps_of_the_disk_in_the_drive_agree(stick: FdsStick) -> None:
    first = dump(stick, sides=ONE_SIDE)
    second = dump(stick, sides=ONE_SIDE)

    payloads = [[block.payload for block in result.sides[0].blocks] for result in (first, second)]
    assert payloads[0] == payloads[1]
    assert first.grade is Grade.CLEAN


def test_a_calibration_reads_the_disk_in_the_drive(stick: FdsStick) -> None:
    result = calibrate(stick, mode=Mode.SPEED, reads=CALIBRATION_READS)

    assert len(result.samples) == CALIBRATION_READS
    assert result.last is not None
    assert result.last.read == result.last.expected


def test_the_calibration_disk_writes_and_reads_back(stick: FdsStick) -> None:
    required(SCRATCH_ENV, "with a scratch disk in the drive, since this overwrites side A")

    report = write_verified(
        stick, stick, calibration_disk(ONE_SIDE), confirm=lambda _: True, backup=None
    )

    assert report.verified


def test_a_quick_surface_pass_holds_on_a_scratch_disk(stick: FdsStick) -> None:
    required(SCRATCH_ENV, "with a scratch disk in the drive, since this overwrites side A")

    report = surface_test(
        stick, stick, sides=ONE_SIDE, confirm=lambda _: True, plan=SurfacePlan(fill=False)
    )

    assert report.passed
