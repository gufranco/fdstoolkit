from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest
from drive_double import FacingDrive, FaultPlan, SimulatedDrive

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.calibration import LARGEST_FACTORY_SIDE, calibration_disk
from fdstoolkit.codecs.fds import SIDE_SIZE, decode
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.edit.files import FileSpec, insert_file
from fdstoolkit.hardware.ports import BlockRead, FaultKind, HardwareFaultError
from fdstoolkit.hardware.session import (
    STALE_BLOCK,
    Grade,
    HalfWriteError,
    LongSideError,
    SideFlipError,
    WriteNotTakenError,
    WriteRefusedError,
    dump,
    dump_repeated,
    refuse_long_sides,
    write_verified,
)


def sample_disk(sides: int = 1) -> Disk:
    disk, _ = decode(blank_image(sides=sides, headered=False, formatted=True, game_name="SMB"))
    return disk


FILES = 5


def disk_with_files(count: int = FILES) -> Disk:
    disk = sample_disk()
    for number in range(count):
        disk = insert_file(
            disk,
            side=0,
            spec=FileSpec(
                name=f"FILE{number}",
                address=0x6000,
                kind=FileKind.PROGRAM,
                data=bytes([number + 1]) * 16,
            ),
        )
    return disk


class DroppingDrive(SimulatedDrive):
    def __init__(self, disk: Disk, *, dropped: int, plan: FaultPlan) -> None:
        super().__init__(disk, plan=plan)
        self.dropped = dropped

    def read_side(self, side: int) -> Iterator[BlockRead]:
        blocks = list(super().read_side(side))
        if self.read_count == 1:
            return iter(blocks)
        return iter(blocks[: self.dropped] + blocks[self.dropped + 1 :])


class ShortFirstReadDrive(SimulatedDrive):
    def __init__(self, disk: Disk, *, kept: int) -> None:
        super().__init__(disk)
        self.kept = kept

    def read_side(self, side: int) -> Iterator[BlockRead]:
        blocks = list(super().read_side(side))
        if self.read_count == 1:
            return iter(blocks[: self.kept])
        return iter(blocks)


def test_a_read_that_stopped_before_the_declared_files_is_read_again() -> None:
    # Arrange
    disk = disk_with_files()
    drive = ShortFirstReadDrive(disk, kept=3)

    # Act
    result = dump(drive, sides=1, retries=2)

    # Assert
    assert drive.read_count == 2
    assert [block.payload for block in result.sides[0].blocks] == [
        block.payload for block in disk.sides[0].blocks
    ]
    assert result.sides[0].marginal_blocks == tuple(range(3, len(disk.sides[0].blocks)))


def test_a_side_that_never_reads_its_declared_files_fails() -> None:
    # Arrange
    drive = ShortFirstReadDrive(disk_with_files(), kept=3)
    result = dump(drive, sides=1, retries=0)

    # Act
    missing = len(disk_with_files().sides[0].blocks) - 3

    # Assert
    assert result.sides[0].grade is Grade.FAILED
    assert result.sides[0].missing_blocks == missing
    assert result.sides[0].lines == (
        f"side 0: {missing} block(s) the side declares were never found, after block 2",
        "side 0: a console stops this side with error 25, block 4 expected",
    )


def test_many_failed_blocks_share_one_retry_budget() -> None:
    # Arrange
    disk = disk_with_files()
    flaky = dict.fromkeys(range(2, len(disk.sides[0].blocks)), 99)
    drive = SimulatedDrive(disk, plan=FaultPlan(flaky_blocks=flaky))

    # Act
    dump(drive, sides=1, retries=3)

    # Assert
    assert len(flaky) > 3
    assert drive.read_count == 4


def test_a_retry_budget_of_nothing_reads_the_side_once() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(bad_crc_blocks=frozenset({1})))

    # Act
    result = dump(drive, sides=1, retries=0)

    # Assert
    assert drive.read_count == 1
    assert result.sides[0].failed_blocks == (1,)


def test_a_clean_side_is_never_read_again() -> None:
    # Arrange
    drive = SimulatedDrive(disk_with_files())

    # Act
    dump(drive, sides=1, retries=3)

    # Assert
    assert drive.read_count == 1


def test_one_re_read_resolves_every_block_that_now_reads_clean() -> None:
    # Arrange
    disk = disk_with_files()
    drive = SimulatedDrive(disk, plan=FaultPlan(flaky_blocks={3: 2, 5: 2, 7: 2}))

    # Act
    result = dump(drive, sides=1, retries=3)

    # Assert
    assert drive.read_count == 2
    assert result.sides[0].marginal_blocks == (3, 5, 7)
    assert result.grade is Grade.MARGINAL


def test_a_re_read_that_loses_an_earlier_block_still_recovers_by_header() -> None:
    # Arrange
    disk = disk_with_files()
    last_data = len(disk.sides[0].blocks) - 1
    drive = DroppingDrive(disk, dropped=3, plan=FaultPlan(flaky_blocks={last_data: 2}))
    result = dump(drive, sides=1, retries=2)

    # Act
    recovered = result.sides[0].blocks[last_data]

    # Assert
    assert recovered.crc_ok
    assert recovered.payload == disk.sides[0].blocks[last_data].payload


def test_a_block_whose_header_is_gone_from_the_re_read_stays_failed() -> None:
    # Arrange
    disk = disk_with_files()
    drive = DroppingDrive(disk, dropped=4, plan=FaultPlan(flaky_blocks={4: 2}))

    # Act
    result = dump(drive, sides=1, retries=1)

    # Assert
    assert result.sides[0].failed_blocks == (4,)
    assert result.sides[0].blocks[4].attempts == 2


def test_a_block_with_no_bytes_cannot_be_matched_and_stays_failed() -> None:
    # Arrange
    class EmptyBlockDrive(SimulatedDrive):
        def read_side(self, side: int) -> Iterator[BlockRead]:
            blocks = list(super().read_side(side))
            blocks[1] = BlockRead(index=1, payload=b"", crc_ok=False, attempts=1)
            return iter(blocks)

    # Act
    result = dump(EmptyBlockDrive(sample_disk()), sides=1, retries=2)

    # Assert
    assert result.sides[0].failed_blocks == (1,)


def test_a_clean_dump_is_graded_clean() -> None:
    # Arrange
    reader = SimulatedDrive(sample_disk())
    sides = 1

    # Act
    result = dump(reader, sides=sides)

    # Assert
    assert result.grade is Grade.CLEAN
    assert result.sides[0].blocks[0].payload[0] == 0x01


def test_a_dump_retries_a_flaky_block_and_grades_it_marginal() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(flaky_blocks={1: 3}))

    # Act
    result = dump(drive, sides=1, retries=3)

    # Assert
    assert result.grade is Grade.MARGINAL
    assert result.sides[0].blocks[1].attempts == 3
    assert result.sides[0].marginal_blocks == (1,)


def longer_than_any_factory_side() -> Disk:
    disk = sample_disk()
    return insert_file(
        disk,
        side=0,
        spec=FileSpec(
            name="LONG",
            address=0x6000,
            kind=FileKind.PROGRAM,
            data=bytes(LARGEST_FACTORY_SIDE),
        ),
    )


def test_a_side_longer_than_any_factory_side_is_refused() -> None:
    # Arrange
    disk = longer_than_any_factory_side()

    # Act
    with pytest.raises(LongSideError, match="54958 bytes") as raised:
        refuse_long_sides(disk)

    # Assert
    assert raised.type is LongSideError


def test_a_side_as_long_as_the_calibration_disk_is_accepted() -> None:
    # Arrange
    disk = calibration_disk()

    # Act
    outcome = refuse_long_sides(disk)

    # Assert
    assert outcome is None


class HeaderLockedDrive(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        kept = self._side(side).blocks[0].payload
        super().write_side(side, [kept, *blocks[1:]])


def test_a_drive_that_keeps_the_nintendo_header_is_named_as_half_modified() -> None:
    # Arrange
    drive = HeaderLockedDrive(disk_with_files())
    image = disk_with_files(2)
    image = Disk(
        sides=(
            Side(
                blocks=(
                    Block(
                        kind=BlockKind.DISK_INFO,
                        payload=decode(
                            blank_image(sides=1, headered=False, formatted=True, game_name="ZEL")
                        )[0]
                        .sides[0]
                        .blocks[0]
                        .payload,
                    ),
                    *image.sides[0].blocks[1:],
                ),
                tail=b"",
                capacity=SIDE_SIZE,
            ),
        )
    )

    # Act
    with pytest.raises(HalfWriteError, match="FMD-POWER") as raised:
        write_verified(drive, drive, image, confirm=lambda _: True, backup=None)

    # Assert
    assert raised.type is HalfWriteError


def test_a_refused_write_names_the_write_protect_tab() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(writes_do_not_stick=True))

    # Act
    with pytest.raises(WriteNotTakenError, match="write-protect tab") as raised:
        write_verified(drive, drive, disk_with_files(), confirm=lambda _: True, backup=None)

    # Assert
    assert raised.type is WriteNotTakenError


def test_a_refused_write_names_the_write_lockout_circuit() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(writes_do_not_stick=True))

    # Act
    with pytest.raises(WriteNotTakenError, match="lockout circuit") as raised:
        write_verified(drive, drive, disk_with_files(), confirm=lambda _: True, backup=None)

    # Assert
    assert raised.type is WriteNotTakenError


class OverlayDrive(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        current = self._side(side)
        kept = [block.payload for block in current.blocks[len(blocks) :]]
        super().write_side(side, [*blocks, *kept])


def test_old_blocks_left_after_a_shorter_image_fail_the_verification() -> None:
    # Arrange
    drive = OverlayDrive(disk_with_files())
    image = disk_with_files(1)
    report = write_verified(drive, drive, image, confirm=lambda _: True, backup=None)

    # Act
    written = len(image.sides[0].blocks)

    # Assert
    assert not report.verified
    assert report.stale_blocks == tuple((0, index) for index in range(written, written + 8))
    assert report.mismatched_blocks == report.stale_blocks
    assert report.lines[0] == f"side 0: block {written} {STALE_BLOCK}"


def test_a_block_that_never_reads_cleanly_fails_the_dump() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(bad_crc_blocks=frozenset({1})))

    # Act
    result = dump(drive, sides=1, retries=2)

    # Assert
    assert result.grade is Grade.FAILED
    assert result.sides[0].failed_blocks == (1,)


def test_a_failing_block_is_still_kept_in_the_dump() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(bad_crc_blocks=frozenset({1})))

    # Act
    result = dump(drive, sides=1, retries=0)

    # Assert
    assert len(result.sides[0].blocks) == 2


def test_a_link_fault_stops_the_dump_immediately() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk(sides=2), plan=FaultPlan(link_lost_after=1))

    # Act
    with pytest.raises(HardwareFaultError) as caught:
        dump(drive, sides=2)

    # Assert
    assert caught.type is HardwareFaultError
    assert caught.value.kind is FaultKind.LINK


def test_a_dump_refuses_to_start_when_the_drive_is_empty() -> None:
    # Arrange
    reader = SimulatedDrive(None)
    sides = 1

    # Act
    with pytest.raises(WriteRefusedError, match="no disk") as raised:
        dump(reader, sides=sides)

    # Assert
    assert raised.type is WriteRefusedError


def test_repeated_reads_of_a_stable_disk_agree() -> None:
    # Arrange
    reader = SimulatedDrive(sample_disk())
    sides = 1
    passes = 3

    # Act
    report = dump_repeated(reader, sides=sides, passes=passes)

    # Assert
    assert report.grade is Grade.CLEAN
    assert report.unstable_blocks == ()


def test_repeated_reads_of_an_unstable_disk_disagree() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(unstable_blocks=frozenset({1})))

    # Act
    report = dump_repeated(drive, sides=1, passes=3)

    # Assert
    assert report.grade is Grade.UNSTABLE
    assert report.unstable_blocks == ((0, 1),)


def test_repeated_reads_need_at_least_two_passes() -> None:
    # Arrange
    reader = SimulatedDrive(sample_disk())
    sides = 1
    passes = 1

    # Act
    with pytest.raises(ValueError, match="at least two passes") as raised:
        dump_repeated(reader, sides=sides, passes=passes)

    # Assert
    assert raised.type is ValueError


def test_a_write_dumps_a_backup_first() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk())
    saved: list[bytes] = []

    # Act
    write_verified(
        drive,
        drive,
        sample_disk(),
        confirm=lambda _: True,
        backup=saved.append,
    )

    # Assert
    assert saved
    assert saved[0][:1] == bytes([0x01])


def test_a_write_stops_when_the_operator_declines() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk())

    # Act
    with pytest.raises(WriteRefusedError, match="declined") as raised:
        write_verified(drive, drive, sample_disk(), confirm=lambda _: False, backup=None)

    # Assert
    assert raised.type is WriteRefusedError
    assert drive.write_count == 0


def test_a_write_stops_on_a_write_protected_disk() -> None:
    # Arrange
    drive = SimulatedDrive(sample_disk(), write_protected=True)

    # Act
    with pytest.raises(WriteRefusedError, match="write protected") as raised:
        write_verified(drive, drive, sample_disk(), confirm=lambda _: True, backup=None)

    # Assert
    assert raised.type is WriteRefusedError


def two_sided_game() -> Disk:
    disk, _ = decode(blank_image(sides=2, headered=False, formatted=True, game_name="ZEL"))
    return disk


def blank_scratch() -> Disk:
    disk, _ = decode(blank_image(sides=2, headered=False, formatted=False))
    return disk


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


def other_game() -> Disk:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="ZEL"))
    return disk


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


class OneFace:
    """A drive whose head reaches whichever face the operator put against it."""

    selects_sides = False

    def __init__(self, disk: Disk) -> None:
        self._inner = SimulatedDrive(disk)
        self.facing = 0

    def status(self):  # noqa: ANN201
        return self._inner.status()

    def read_side(self, side: int):  # noqa: ANN201, ARG002
        return self._inner.read_side(self.facing)


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


class MiddleLostDrive(SimulatedDrive):
    def read_side(self, side: int) -> Iterator[BlockRead]:
        blocks = list(super().read_side(side))
        if self.read_count == 1:
            return iter(blocks[:3] + blocks[5:])
        return iter(blocks)


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
