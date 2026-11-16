from __future__ import annotations

import pytest
from drive_double import FacingDrive, SimulatedDrive
from session_kit import blank_scratch, sample_disk, two_sided_game

from fdstoolkit.codecs.fds import decode
from fdstoolkit.hardware.session import (
    Grade,
    SideFlipError,
    dump,
)
from fdstoolkit.hardware.writing import write_verified


def test_a_two_side_image_is_written_with_one_turn_of_the_disk() -> None:
    # Arrange
    drive = FacingDrive(sample_disk(sides=2))
    saved: list[bytes] = []

    # Act
    report = write_verified(
        drive,
        drive,
        two_sided_game(),
        confirm=lambda _: True,
        backup=saved.append,
        flip=drive.turn,
    )

    # Assert
    assert report.verified
    assert drive.turns == 1
    assert drive.disk is not None
    assert drive.disk.sides == two_sided_game().sides
    assert decode(saved[-1])[0].side_count == 2


def test_a_two_side_write_onto_a_blank_disk_still_tells_the_faces_apart() -> None:
    # Arrange
    drive = FacingDrive(blank_scratch())

    # Act
    report = write_verified(
        drive, drive, two_sided_game(), confirm=lambda _: True, backup=None, flip=drive.turn
    )

    # Assert
    assert report.verified


def test_a_disk_that_was_not_turned_over_stops_before_the_second_side() -> None:
    # Arrange
    drive = FacingDrive(sample_disk(sides=2))

    # Act
    with pytest.raises(SideFlipError, match="not turned over") as raised:
        write_verified(
            drive, drive, two_sided_game(), confirm=lambda _: True, backup=None, flip=lambda _: True
        )

    # Assert
    assert raised.type is SideFlipError
    assert drive.write_count == 1


def test_a_declined_turn_stops_the_write_after_the_first_side() -> None:
    # Arrange
    drive = FacingDrive(sample_disk(sides=2))

    # Act
    with pytest.raises(SideFlipError, match="declined") as raised:
        write_verified(
            drive,
            drive,
            two_sided_game(),
            confirm=lambda _: True,
            backup=None,
            flip=lambda _: False,
        )

    # Assert
    assert raised.type is SideFlipError
    assert drive.write_count == 1


def test_a_two_side_write_with_nobody_to_turn_the_disk_is_refused_before_writing() -> None:
    # Arrange
    drive = FacingDrive(sample_disk(sides=2))

    # Act
    with pytest.raises(SideFlipError, match="turned over") as raised:
        write_verified(drive, drive, two_sided_game(), confirm=lambda _: True, backup=None)

    # Assert
    assert raised.type is SideFlipError
    assert drive.write_count == 0


def test_a_drive_that_selects_sides_writes_both_without_being_asked() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk(sides=2))
    asked: list[str] = []

    # Act
    report = write_verified(
        drive,
        drive,
        two_sided_game(),
        confirm=lambda _: True,
        backup=None,
        flip=lambda message: bool(asked.append(message)) or True,
    )

    # Assert
    assert report.verified
    assert asked == []


def test_a_write_reports_each_step_as_it_goes() -> None:
    # Arrange
    drive = FacingDrive(sample_disk(sides=2))
    steps: list[str] = []

    # Act
    write_verified(
        drive,
        drive,
        two_sided_game(),
        confirm=lambda _: True,
        backup=None,
        flip=drive.turn,
        progress=steps.append,
    )

    # Assert
    assert steps == [
        "reading side 0 before writing it",
        "writing side 0",
        "reading side 0 back",
        "reading side 1 before writing it",
        "writing side 1",
        "reading side 1 back",
    ]


def test_a_dump_reports_each_side_as_it_reads_it() -> None:
    # Arrange
    drive = FacingDrive(sample_disk(sides=2))
    steps: list[str] = []

    # Act
    dump(drive, sides=2, flip=drive.turn, progress=steps.append)

    # Assert
    assert steps == ["reading side 0", "reading side 1"]


def test_a_verified_write_reads_the_disk_back() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk())

    # Act
    report = write_verified(drive, drive, sample_disk(), confirm=lambda _: True, backup=None)

    # Assert
    assert report.verified
    assert report.grade is Grade.CLEAN
    assert drive.read_count >= 2
