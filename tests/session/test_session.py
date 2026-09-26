from __future__ import annotations

from collections.abc import Iterator

import pytest
from drive_double import FacingDrive, FaultPlan, SimulatedDrive

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import SIDE_SIZE, decode
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.edit.files import FileSpec, insert_file
from fdstoolkit.hardware.ports import BlockRead, FaultKind, HardwareFaultError
from fdstoolkit.hardware.session import (
    Grade,
    SideFlipError,
    WriteNotTakenError,
    WriteRefusedError,
    dump,
    dump_repeated,
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


def test_many_failed_blocks_share_one_retry_budget() -> None:
    disk = disk_with_files()
    flaky = dict.fromkeys(range(2, len(disk.sides[0].blocks)), 99)
    drive = SimulatedDrive(disk, plan=FaultPlan(flaky_blocks=flaky))

    dump(drive, sides=1, retries=3)

    assert len(flaky) > 3
    assert drive.read_count == 4


def test_a_retry_budget_of_nothing_reads_the_side_once() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(bad_crc_blocks=frozenset({1})))

    result = dump(drive, sides=1, retries=0)

    assert drive.read_count == 1
    assert result.sides[0].failed_blocks == (1,)


def test_a_clean_side_is_never_read_again() -> None:
    drive = SimulatedDrive(disk_with_files())

    dump(drive, sides=1, retries=3)

    assert drive.read_count == 1


def test_one_re_read_resolves_every_block_that_now_reads_clean() -> None:
    disk = disk_with_files()
    drive = SimulatedDrive(disk, plan=FaultPlan(flaky_blocks={3: 2, 5: 2, 7: 2}))

    result = dump(drive, sides=1, retries=3)

    assert drive.read_count == 2
    assert result.sides[0].marginal_blocks == (3, 5, 7)
    assert result.grade is Grade.MARGINAL


def test_a_re_read_that_loses_an_earlier_block_still_recovers_by_header() -> None:
    disk = disk_with_files()
    last_data = len(disk.sides[0].blocks) - 1
    drive = DroppingDrive(disk, dropped=3, plan=FaultPlan(flaky_blocks={last_data: 2}))

    result = dump(drive, sides=1, retries=2)

    recovered = result.sides[0].blocks[last_data]
    assert recovered.crc_ok
    assert recovered.payload == disk.sides[0].blocks[last_data].payload


def test_a_block_whose_header_is_gone_from_the_re_read_stays_failed() -> None:
    disk = disk_with_files()
    drive = DroppingDrive(disk, dropped=4, plan=FaultPlan(flaky_blocks={4: 2}))

    result = dump(drive, sides=1, retries=1)

    assert result.sides[0].failed_blocks == (4,)
    assert result.sides[0].blocks[4].attempts == 2


def test_a_block_with_no_bytes_cannot_be_matched_and_stays_failed() -> None:
    class EmptyBlockDrive(SimulatedDrive):
        def read_side(self, side: int) -> Iterator[BlockRead]:
            blocks = list(super().read_side(side))
            blocks[1] = BlockRead(index=1, payload=b"", crc_ok=False, attempts=1)
            return iter(blocks)

    result = dump(EmptyBlockDrive(sample_disk()), sides=1, retries=2)

    assert result.sides[0].failed_blocks == (1,)


def test_a_clean_dump_is_graded_clean() -> None:
    result = dump(SimulatedDrive(sample_disk()), sides=1)

    assert result.grade is Grade.CLEAN
    assert result.sides[0].blocks[0].payload[0] == 0x01


def test_a_dump_retries_a_flaky_block_and_grades_it_marginal() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(flaky_blocks={1: 3}))

    result = dump(drive, sides=1, retries=3)

    assert result.grade is Grade.MARGINAL
    assert result.sides[0].blocks[1].attempts == 3
    assert result.sides[0].marginal_blocks == (1,)


def test_a_block_that_never_reads_cleanly_fails_the_dump() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(bad_crc_blocks=frozenset({1})))

    result = dump(drive, sides=1, retries=2)

    assert result.grade is Grade.FAILED
    assert result.sides[0].failed_blocks == (1,)


def test_a_failing_block_is_still_kept_in_the_dump() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(bad_crc_blocks=frozenset({1})))

    result = dump(drive, sides=1, retries=0)

    assert len(result.sides[0].blocks) == 2


def test_a_link_fault_stops_the_dump_immediately() -> None:
    drive = SimulatedDrive(sample_disk(sides=2), plan=FaultPlan(link_lost_after=1))

    with pytest.raises(HardwareFaultError) as caught:
        dump(drive, sides=2)

    assert caught.value.kind is FaultKind.LINK


def test_a_dump_refuses_to_start_when_the_drive_is_empty() -> None:
    with pytest.raises(WriteRefusedError, match="no disk"):
        dump(SimulatedDrive(None), sides=1)


def test_repeated_reads_of_a_stable_disk_agree() -> None:
    report = dump_repeated(SimulatedDrive(sample_disk()), sides=1, passes=3)

    assert report.grade is Grade.CLEAN
    assert report.unstable_blocks == ()


def test_repeated_reads_of_an_unstable_disk_disagree() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(unstable_blocks=frozenset({1})))

    report = dump_repeated(drive, sides=1, passes=3)

    assert report.grade is Grade.UNSTABLE
    assert report.unstable_blocks == ((0, 1),)


def test_repeated_reads_need_at_least_two_passes() -> None:
    with pytest.raises(ValueError, match="at least two passes"):
        dump_repeated(SimulatedDrive(sample_disk()), sides=1, passes=1)


def test_a_write_dumps_a_backup_first() -> None:
    drive = SimulatedDrive(sample_disk())
    saved: list[bytes] = []

    write_verified(
        drive,
        drive,
        sample_disk(),
        confirm=lambda _: True,
        backup=saved.append,
    )

    assert saved
    assert saved[0][:1] == bytes([0x01])


def test_a_write_stops_when_the_operator_declines() -> None:
    drive = SimulatedDrive(sample_disk())

    with pytest.raises(WriteRefusedError, match="declined"):
        write_verified(drive, drive, sample_disk(), confirm=lambda _: False, backup=None)

    assert drive.write_count == 0


def test_a_write_stops_on_a_write_protected_disk() -> None:
    drive = SimulatedDrive(sample_disk(), write_protected=True)

    with pytest.raises(WriteRefusedError, match="write protected"):
        write_verified(drive, drive, sample_disk(), confirm=lambda _: True, backup=None)


def two_sided_game() -> Disk:
    disk, _ = decode(blank_image(sides=2, headered=False, formatted=True, game_name="ZEL"))
    return disk


def blank_scratch() -> Disk:
    disk, _ = decode(blank_image(sides=2, headered=False, formatted=False))
    return disk


def test_a_two_side_image_is_written_with_one_turn_of_the_disk() -> None:
    drive = FacingDrive(sample_disk(sides=2))
    saved: list[bytes] = []

    report = write_verified(
        drive,
        drive,
        two_sided_game(),
        confirm=lambda _: True,
        backup=saved.append,
        flip=drive.turn,
    )

    assert report.verified
    assert drive.turns == 1
    assert drive.disk is not None
    assert drive.disk.sides == two_sided_game().sides
    assert decode(saved[-1])[0].side_count == 2


def test_a_two_side_write_onto_a_blank_disk_still_tells_the_faces_apart() -> None:
    drive = FacingDrive(blank_scratch())

    report = write_verified(
        drive, drive, two_sided_game(), confirm=lambda _: True, backup=None, flip=drive.turn
    )

    assert report.verified


def test_a_disk_that_was_not_turned_over_stops_before_the_second_side() -> None:
    drive = FacingDrive(sample_disk(sides=2))

    with pytest.raises(SideFlipError, match="not turned over"):
        write_verified(
            drive, drive, two_sided_game(), confirm=lambda _: True, backup=None, flip=lambda _: True
        )

    assert drive.write_count == 1


def test_a_declined_turn_stops_the_write_after_the_first_side() -> None:
    drive = FacingDrive(sample_disk(sides=2))

    with pytest.raises(SideFlipError, match="declined"):
        write_verified(
            drive,
            drive,
            two_sided_game(),
            confirm=lambda _: True,
            backup=None,
            flip=lambda _: False,
        )

    assert drive.write_count == 1


def test_a_two_side_write_with_nobody_to_turn_the_disk_is_refused_before_writing() -> None:
    drive = FacingDrive(sample_disk(sides=2))

    with pytest.raises(SideFlipError, match="turned over"):
        write_verified(drive, drive, two_sided_game(), confirm=lambda _: True, backup=None)

    assert drive.write_count == 0


def test_a_drive_that_selects_sides_writes_both_without_being_asked() -> None:
    drive = SimulatedDrive(sample_disk(sides=2))
    asked: list[str] = []

    report = write_verified(
        drive,
        drive,
        two_sided_game(),
        confirm=lambda _: True,
        backup=None,
        flip=lambda message: bool(asked.append(message)) or True,
    )

    assert report.verified
    assert asked == []


def test_a_write_reports_each_step_as_it_goes() -> None:
    drive = FacingDrive(sample_disk(sides=2))
    steps: list[str] = []

    write_verified(
        drive,
        drive,
        two_sided_game(),
        confirm=lambda _: True,
        backup=None,
        flip=drive.turn,
        progress=steps.append,
    )

    assert steps == [
        "reading side 0 before writing it",
        "writing side 0",
        "reading side 0 back",
        "reading side 1 before writing it",
        "writing side 1",
        "reading side 1 back",
    ]


def test_a_dump_reports_each_side_as_it_reads_it() -> None:
    drive = FacingDrive(sample_disk(sides=2))
    steps: list[str] = []

    dump(drive, sides=2, flip=drive.turn, progress=steps.append)

    assert steps == ["reading side 0", "reading side 1"]


def test_a_verified_write_reads_the_disk_back() -> None:
    drive = SimulatedDrive(sample_disk())

    report = write_verified(drive, drive, sample_disk(), confirm=lambda _: True, backup=None)

    assert report.verified
    assert report.grade is Grade.CLEAN
    assert drive.read_count >= 2


def other_game() -> Disk:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="ZEL"))
    return disk


def test_a_write_the_disk_did_not_take_stops_as_refused() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(writes_do_not_stick=True))

    with pytest.raises(WriteNotTakenError, match="reads back exactly as it was before") as caught:
        write_verified(drive, drive, other_game(), confirm=lambda _: True, backup=None)

    assert "FD3206" in str(caught.value)


def test_the_disk_is_read_once_before_a_write() -> None:
    drive = SimulatedDrive(sample_disk())
    saved: list[bytes] = []

    write_verified(drive, drive, other_game(), confirm=lambda _: True, backup=saved.append)

    assert drive.read_count == 2
    assert len(saved) == 1


def test_a_write_of_the_same_contents_is_not_mistaken_for_a_refusal() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(writes_do_not_stick=True))

    report = write_verified(drive, drive, sample_disk(), confirm=lambda _: True, backup=None)

    assert report.verified


def test_a_verified_write_carries_the_portability_caveat() -> None:
    drive = SimulatedDrive(sample_disk())

    report = write_verified(drive, drive, other_game(), confirm=lambda _: True, backup=None)

    assert report.verified
    assert any("second drive" in note for note in report.notes)


def test_a_write_that_changed_the_disk_wrongly_is_not_blamed_on_the_controller() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(unstable_blocks=frozenset({1})))

    report = write_verified(drive, drive, sample_disk(), confirm=lambda _: True, backup=None)

    assert not report.verified
    assert report.notes == ()


def test_a_write_reports_which_blocks_differ_after_the_read_back() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(unstable_blocks=frozenset({1})))

    report = write_verified(drive, drive, sample_disk(), confirm=lambda _: True, backup=None)

    assert not report.verified
    assert report.mismatched_blocks == ((0, 1),)
    assert report.grade is Grade.FAILED


def test_the_confirmation_message_names_what_is_at_stake() -> None:
    drive = SimulatedDrive(sample_disk())
    seen: list[str] = []

    def confirm(message: str) -> bool:
        seen.append(message)
        return True

    write_verified(drive, drive, sample_disk(), confirm=confirm, backup=None)

    assert "overwrite" in seen[0]
    assert "side" in seen[0]


def test_a_fault_during_the_write_stops_the_run() -> None:
    class RefusingDrive(SimulatedDrive):
        def write_side(self, side: int, blocks: object) -> None:
            del side, blocks
            message = "the drive stopped answering"
            raise HardwareFaultError(message, kind=FaultKind.LINK)

    drive = RefusingDrive(sample_disk())

    with pytest.raises(WriteRefusedError, match="the write stopped at side 0"):
        write_verified(drive, drive, sample_disk(), confirm=lambda _: True, backup=None)


def test_a_write_refuses_an_image_that_cannot_fit_a_disk() -> None:
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

    with pytest.raises(WriteRefusedError, match="does not fit a disk"):
        write_verified(drive, drive, stuffed, confirm=lambda _: True, backup=None)


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
    drive = OneFace(sample_disk(sides=2))
    asked: list[str] = []

    def flip(message: str) -> bool:
        asked.append(message)
        drive.facing = 1
        return True

    dump(drive, sides=2, flip=flip)

    assert len(asked) == 1
    assert "turn the disk over" in asked[0]
    assert "side B" in asked[0]


def test_a_single_face_drive_refuses_two_sides_with_no_operator() -> None:
    drive = OneFace(sample_disk(sides=2))

    with pytest.raises(SideFlipError, match="turned over"):
        dump(drive, sides=2)


def test_a_declined_flip_stops_the_dump() -> None:
    drive = OneFace(sample_disk(sides=2))

    with pytest.raises(SideFlipError, match="declined"):
        dump(drive, sides=2, flip=lambda _: False)


def test_a_disk_that_was_not_turned_over_is_caught() -> None:
    drive = OneFace(sample_disk(sides=2))

    with pytest.raises(SideFlipError, match="not turned over"):
        dump(drive, sides=2, flip=lambda _: True)


def test_two_unreadable_sides_are_failed_reads_rather_than_an_unturned_disk() -> None:
    empty = Side(blocks=(), tail=b"", capacity=SIDE_SIZE)
    drive = FacingDrive(Disk(sides=(empty, empty)))

    result = dump(drive, sides=2, flip=drive.turn)

    assert drive.turns == 1
    assert [side.grade for side in result.sides] == [Grade.FAILED, Grade.FAILED]


def test_a_single_face_drive_reads_one_side_without_being_asked() -> None:
    drive = OneFace(sample_disk(sides=2))

    result = dump(drive, sides=1)

    assert len(result.sides) == 1


def test_a_drive_that_selects_sides_is_never_asked_to_flip() -> None:
    asked: list[str] = []

    result = dump(
        SimulatedDrive(sample_disk(sides=2)), sides=2, flip=lambda m: bool(asked.append(m)) or True
    )

    assert asked == []
    assert len(result.sides) == 2


def test_repeated_passes_ask_for_the_flip_on_every_pass() -> None:
    drive = OneFace(sample_disk(sides=2))
    asked: list[str] = []

    def flip(message: str) -> bool:
        asked.append(message)
        drive.facing = 1 - drive.facing
        return True

    dump_repeated(drive, sides=2, passes=2, flip=flip)

    assert len(asked) == 3
    assert "back over" in asked[1]


def test_repeated_passes_refuse_when_the_disk_is_not_returned_to_side_a() -> None:
    drive = OneFace(sample_disk(sides=2))
    answers = iter([True, False])

    def flip(message: str) -> bool:
        del message
        answer = next(answers)
        if answer:
            drive.facing = 1
        return answer

    with pytest.raises(SideFlipError, match="returned to side A"):
        dump_repeated(drive, sides=2, passes=2, flip=flip)


def test_repeated_passes_on_one_side_need_no_flip() -> None:
    drive = OneFace(sample_disk(sides=2))

    report = dump_repeated(drive, sides=1, passes=2)

    assert report.unstable_blocks == ()
