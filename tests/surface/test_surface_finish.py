from __future__ import annotations

import pytest
from drive_double import FacingDrive, SimulatedDrive
from surface_kit import BLANK_BLOCKS, FinishRefusingDrive, scratch_disk, two_sided_scratch

from fdstoolkit.build.blank import formatted_side
from fdstoolkit.codecs.fds import encode
from fdstoolkit.hardware.session import MAX_PASSES
from fdstoolkit.quality.surface import (
    PATTERNS,
    Finish,
    SurfacePlan,
    SurfaceTestRefusedError,
    blank_disk,
    surface_test,
)


def test_the_default_finish_leaves_the_last_pattern_on_the_disk() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk())

    # Act
    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    # Assert
    assert report.finish is Finish.LEAVE
    assert drive.disk is not None
    assert drive.disk.sides[0].blocks
    assert len(drive.disk.sides[0].blocks) > BLANK_BLOCKS


def test_a_blank_finish_leaves_the_disk_as_it_left_the_kiosk() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk())

    # Act
    report = surface_test(
        drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(finish=Finish.BLANK)
    )

    # Assert
    assert report.finish_verified
    assert drive.disk is not None
    assert len(drive.disk.sides[0].blocks) == BLANK_BLOCKS


def test_a_blank_finish_matches_the_factory_side_byte_for_byte() -> None:
    # Arrange
    disk = blank_disk(sides=1, game_name="   ")

    # Act
    data, _ = encode(disk, headered=False)

    # Assert
    assert data == formatted_side(side=0, disk_number=0, game_name="   ")


def test_an_erase_finish_leaves_nothing_the_adapter_can_read() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk())

    # Act
    surface_test(
        drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(finish=Finish.ERASE)
    )

    # Assert
    assert drive.disk is not None
    assert drive.disk.sides[0].blocks == ()


def test_a_finish_that_does_not_stick_is_reported() -> None:
    # Arrange
    drive = FinishRefusingDrive(scratch_disk())

    # Act
    report = surface_test(
        drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(finish=Finish.BLANK)
    )

    # Assert
    assert report.stopped is None
    assert report.finish_ran
    assert not report.finish_verified
    assert not report.passed
    assert "did not take the write" in report.finish_problem


def test_a_surface_test_past_the_largest_pass_count_is_refused() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk())

    # Act
    with pytest.raises(SurfaceTestRefusedError, match="at most") as raised:
        surface_test(
            drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(rounds=MAX_PASSES + 1)
        )

    # Assert
    assert raised.type is SurfaceTestRefusedError
    assert drive.write_count == 0


def test_a_two_side_surface_test_turns_the_disk_once() -> None:
    # Arrange
    drive = FacingDrive(two_sided_scratch())

    # Act
    report = surface_test(drive, drive, sides=2, confirm=lambda _: True, flip=drive.turn)

    # Assert
    assert drive.turns == 1
    assert len(report.passes) == 2 * len(PATTERNS)
    assert {entry.side for entry in report.passes} == {0, 1}
    assert report.passed


def test_a_two_side_blank_finish_turns_back_and_leaves_both_faces_blank() -> None:
    # Arrange
    drive = FacingDrive(two_sided_scratch())

    # Act
    report = surface_test(
        drive,
        drive,
        sides=2,
        confirm=lambda _: True,
        flip=drive.turn,
        plan=SurfacePlan(finish=Finish.BLANK),
    )

    # Assert
    assert report.finish_verified
    assert drive.turns == 2
    assert drive.disk is not None
    assert drive.disk.sides == blank_disk(sides=2).sides


def test_a_finish_whose_turn_was_skipped_writes_nothing_and_says_why() -> None:
    # Arrange
    drive = FacingDrive(two_sided_scratch())
    turns = iter([True, False])

    def turn_once(message: str) -> bool:
        return drive.turn(message) if next(turns) else True

    # Act
    report = surface_test(
        drive,
        drive,
        sides=2,
        confirm=lambda _: True,
        flip=turn_once,
        plan=SurfacePlan(finish=Finish.BLANK),
    )

    # Assert
    assert not report.finish_verified
    assert "not turned over" in report.finish_problem
    assert drive.write_count == 2 * len(PATTERNS) + 1
    assert drive.disk is not None
    assert drive.disk.sides[1] == blank_disk(sides=2).sides[1]
