from __future__ import annotations

import pytest
from drive_double import FacingDrive, FaultPlan, SimulatedDrive
from session_kit import (
    DroppingDrive,
    MiddleLostDrive,
    OneFace,
    ShortFirstReadDrive,
    disk_with_files,
    other_game,
    sample_disk,
)

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import SIDE_SIZE, Disk, Side
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError
from fdstoolkit.hardware.session import (
    Grade,
    SideFlipError,
    WriteNotTakenError,
    WriteRefusedError,
    dump,
    dump_repeated,
)
from fdstoolkit.hardware.writing import write_verified


def test_a_write_the_disk_did_not_take_stops_as_refused() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(writes_do_not_stick=True))

    # Act
    with pytest.raises(WriteNotTakenError, match="reads back exactly as it was before") as caught:
        write_verified(drive, drive, other_game(), confirm=lambda _: True, backup=None)

    # Assert
    assert caught.type is WriteNotTakenError
    assert "FD3206" in str(caught.value)


def test_the_disk_is_read_once_before_a_write() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk())
    saved: list[bytes] = []

    # Act
    write_verified(drive, drive, other_game(), confirm=lambda _: True, backup=saved.append)

    # Assert
    assert drive.read_count == 2
    assert len(saved) == 1


def test_a_write_of_the_same_contents_is_not_mistaken_for_a_refusal() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(writes_do_not_stick=True))

    # Act
    report = write_verified(drive, drive, sample_disk(), confirm=lambda _: True, backup=None)

    # Assert
    assert report.verified


def test_a_verified_write_carries_the_portability_caveat() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk())

    # Act
    report = write_verified(drive, drive, other_game(), confirm=lambda _: True, backup=None)

    # Assert
    assert report.verified
    assert any("second drive" in note for note in report.notes)


def test_a_write_that_changed_the_disk_wrongly_is_not_blamed_on_the_controller() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(unstable_blocks=frozenset({1})))

    # Act
    report = write_verified(drive, drive, sample_disk(), confirm=lambda _: True, backup=None)

    # Assert
    assert not report.verified
    assert report.notes == ()


def test_a_write_reports_which_blocks_differ_after_the_read_back() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(unstable_blocks=frozenset({1})))

    # Act
    report = write_verified(drive, drive, sample_disk(), confirm=lambda _: True, backup=None)

    # Assert
    assert not report.verified
    assert report.mismatched_blocks == ((0, 1),)
    assert report.grade is Grade.FAILED


def test_the_confirmation_message_names_what_is_at_stake() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk())
    seen: list[str] = []

    def confirm(message: str) -> bool:
        seen.append(message)
        return True

    # Act
    write_verified(drive, drive, sample_disk(), confirm=confirm, backup=None)

    # Assert
    assert "overwrite" in seen[0]
    assert "side" in seen[0]


def test_a_fault_during_the_write_stops_the_run() -> None:
    # Arrange
    class RefusingDrive(SimulatedDrive):
        def write_side(self, side: int, blocks: object) -> None:
            del side, blocks
            message = "the drive stopped answering"
            raise HardwareFaultError(message, kind=FaultKind.LINK)

    drive = RefusingDrive(sample_disk())

    # Act
    with pytest.raises(WriteRefusedError, match="the write stopped at side 0") as raised:
        write_verified(drive, drive, sample_disk(), confirm=lambda _: True, backup=None)

    # Assert
    assert raised.type is WriteRefusedError


def test_a_write_refuses_an_image_that_cannot_fit_a_disk() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk())
    crowded = sample_disk().sides[0]
    stuffed = Disk(
        sides=(
            crowded.__class__(
                blocks=crowded.blocks * 400,
                tail=b"",
                capacity=crowded.capacity,
            ),
        )
    )

    # Act
    with pytest.raises(WriteRefusedError, match="does not fit a disk") as raised:
        write_verified(drive, drive, stuffed, confirm=lambda _: True, backup=None)

    # Assert
    assert raised.type is WriteRefusedError


def test_a_single_face_drive_asks_for_the_flip_before_the_second_side() -> None:
    # Arrange
    drive = OneFace(sample_disk(sides=2))
    asked: list[str] = []

    def flip(message: str) -> bool:
        asked.append(message)
        drive.facing = 1
        return True

    # Act
    dump(drive, sides=2, flip=flip)

    # Assert
    assert len(asked) == 1
    assert "turn the disk over" in asked[0]
    assert "side B" in asked[0]


def test_a_single_face_drive_refuses_two_sides_with_no_operator() -> None:
    # Arrange
    drive = OneFace(sample_disk(sides=2))

    # Act
    with pytest.raises(SideFlipError, match="turned over") as raised:
        dump(drive, sides=2)

    # Assert
    assert raised.type is SideFlipError


def test_a_declined_flip_stops_the_dump() -> None:
    # Arrange
    drive = OneFace(sample_disk(sides=2))

    # Act
    with pytest.raises(SideFlipError, match="declined") as raised:
        dump(drive, sides=2, flip=lambda _: False)

    # Assert
    assert raised.type is SideFlipError


def test_a_disk_that_was_not_turned_over_is_caught() -> None:
    # Arrange
    drive = OneFace(sample_disk(sides=2))

    # Act
    with pytest.raises(SideFlipError, match="not turned over") as raised:
        dump(drive, sides=2, flip=lambda _: True)

    # Assert
    assert raised.type is SideFlipError


def test_two_unreadable_sides_are_failed_reads_rather_than_an_unturned_disk() -> None:
    # Arrange
    empty = Side(blocks=(), tail=b"", capacity=SIDE_SIZE)
    drive = FacingDrive(Disk(sides=(empty, empty)))

    # Act
    result = dump(drive, sides=2, flip=drive.turn)

    # Assert
    assert drive.turns == 1
    assert [side.grade for side in result.sides] == [Grade.FAILED, Grade.FAILED]
    assert result.sides[0].console_error == 0x22


def test_a_single_face_drive_reads_one_side_without_being_asked() -> None:
    # Arrange
    drive = OneFace(sample_disk(sides=2))

    # Act
    result = dump(drive, sides=1)

    # Assert
    assert len(result.sides) == 1


def test_a_drive_that_selects_sides_is_never_asked_to_flip() -> None:
    # Arrange
    asked: list[str] = []

    # Act
    result = dump(
        SimulatedDrive(sample_disk(sides=2)), sides=2, flip=lambda m: bool(asked.append(m)) or True
    )

    # Assert
    assert asked == []
    assert len(result.sides) == 2


def test_repeated_passes_ask_for_the_flip_on_every_pass() -> None:
    # Arrange
    drive = OneFace(sample_disk(sides=2))
    asked: list[str] = []

    def flip(message: str) -> bool:
        asked.append(message)
        drive.facing = 1 - drive.facing
        return True

    # Act
    dump_repeated(drive, sides=2, passes=2, flip=flip)

    # Assert
    assert len(asked) == 3
    assert "back over" in asked[1]


def test_repeated_passes_refuse_when_the_disk_is_not_returned_to_side_a() -> None:
    # Arrange
    drive = OneFace(sample_disk(sides=2))
    answers = iter([True, False])

    def flip(message: str) -> bool:
        del message
        answer = next(answers)
        if answer:
            drive.facing = 1
        return answer

    # Act
    with pytest.raises(SideFlipError, match="returned to side A") as raised:
        dump_repeated(drive, sides=2, passes=2, flip=flip)

    # Assert
    assert raised.type is SideFlipError


def test_repeated_passes_on_one_side_need_no_flip() -> None:
    # Arrange
    drive = OneFace(sample_disk(sides=2))

    # Act
    report = dump_repeated(drive, sides=1, passes=2)

    # Assert
    assert report.unstable_blocks == ()


def test_a_side_whose_disk_information_names_the_other_side_is_named() -> None:
    # Arrange
    disk = sample_disk(sides=2)
    swapped = Disk(sides=(disk.sides[1], disk.sides[0]))

    # Act
    result = dump(SimulatedDrive(swapped), sides=2)

    # Assert
    assert result.sides[0].lines == (
        (
            "side 0: its disk information says side B, so the disk may be in the drive with "
            "side B's label up"
        ),
    )
    assert result.sides[1].lines[0].startswith("side 1: its disk information says side A")


def test_a_write_names_a_side_whose_disk_information_names_the_other_side() -> None:
    # Arrange
    disk = sample_disk(sides=2)
    drive = SimulatedDrive(Disk(sides=(disk.sides[1], disk.sides[0])))
    steps: list[str] = []

    # Act
    write_verified(
        drive, drive, sample_disk(), confirm=lambda _: True, backup=None, progress=steps.append
    )

    # Assert
    assert any("its disk information says side B" in step for step in steps)


def test_a_side_with_a_failed_block_names_the_console_error() -> None:
    # Arrange
    drive = SimulatedDrive(disk_with_files(), plan=FaultPlan(bad_crc_blocks=frozenset({3})))

    # Act
    result = dump(drive, sides=1, retries=0)

    # Assert
    assert result.sides[0].console_error == 0x27
    assert "side 0: a console stops this side with error 27, block failed CRC" in (
        result.sides[0].lines
    )


def test_a_side_that_stops_early_names_the_block_the_console_expected() -> None:
    # Arrange
    drive = ShortFirstReadDrive(disk_with_files(), kept=3)

    # Act
    result = dump(drive, sides=1, retries=0)

    # Assert
    assert result.sides[0].console_error == 0x25


def test_a_clean_side_names_no_console_error() -> None:
    # Arrange
    reader = SimulatedDrive(disk_with_files())
    sides = 1

    # Act
    result = dump(reader, sides=sides)

    # Assert
    assert result.sides[0].console_error is None
    assert result.sides[0].lines == ()


def test_a_block_that_reads_back_with_a_bad_checksum_fails_the_write() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(bad_crc_blocks=frozenset({1})))

    # Act
    report = write_verified(drive, drive, disk_with_files(), confirm=lambda _: True, backup=None)

    # Assert
    assert not report.verified
    assert (0, 1) in report.mismatched_blocks


def test_a_pass_that_missed_a_block_does_not_shift_the_blocks_after_it() -> None:
    # Arrange
    disk = disk_with_files()
    drive = DroppingDrive(disk, dropped=3, plan=FaultPlan())

    # Act
    report = dump_repeated(drive, sides=1, passes=2, retries=0)

    # Assert
    assert report.unstable_blocks == ()


def test_blocks_found_on_a_re_read_keep_their_place_on_the_side() -> None:
    # Arrange
    disk = disk_with_files()
    drive = MiddleLostDrive(disk)

    # Act
    result = dump(drive, sides=1, retries=1)

    # Assert
    assert [block.payload for block in result.sides[0].blocks] == [
        block.payload for block in disk.sides[0].blocks
    ]
    assert [block.index for block in result.sides[0].blocks] == list(
        range(len(disk.sides[0].blocks))
    )


def test_a_failed_hidden_block_raises_no_console_error() -> None:
    # Arrange
    disk = disk_with_files(2)
    side = disk.sides[0]
    amount = Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([BlockKind.FILE_AMOUNT, 1]))
    hidden = Disk(
        sides=(
            Side(blocks=(side.blocks[0], amount, *side.blocks[2:]), tail=b"", capacity=SIDE_SIZE),
        )
    )
    drive = SimulatedDrive(hidden, plan=FaultPlan(bad_crc_blocks=frozenset({5})))

    # Act
    result = dump(drive, sides=1, retries=0)

    # Assert
    assert result.sides[0].failed_blocks == (5,)
    assert result.sides[0].console_error is None
