from __future__ import annotations

import time

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.disk import Disk
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError
from fdstoolkit.hardware.session import (
    Grade,
    WriteRefusedError,
    dump,
    dump_repeated,
    write_verified,
)
from fdstoolkit.hardware.simulation import FaultPlan, SimulatedDrive


def sample_disk(sides: int = 1) -> Disk:
    disk, _ = decode(blank_image(sides=sides, headered=False, formatted=True, game_name="SMB"))
    return disk


def test_a_clean_dump_is_graded_clean() -> None:
    result = dump(SimulatedDrive(sample_disk()), sides=1)

    assert result.grade is Grade.CLEAN
    assert result.sides[0].blocks[0].payload[0] == 0x01


def test_a_dump_retries_a_flaky_block_and_grades_it_marginal() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(flaky_blocks={1: 3}))

    result = dump(drive, sides=1, retries=4)

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

    result = dump(drive, sides=1, retries=1)

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


def test_a_write_stops_when_the_image_has_more_sides_than_the_disk() -> None:
    drive = SimulatedDrive(sample_disk(sides=1))

    with pytest.raises(WriteRefusedError, match="2 side"):
        write_verified(drive, drive, sample_disk(sides=2), confirm=lambda _: True, backup=None)


def test_a_verified_write_reads_the_disk_back() -> None:
    drive = SimulatedDrive(sample_disk())

    report = write_verified(drive, drive, sample_disk(), confirm=lambda _: True, backup=None)

    assert report.verified
    assert report.grade is Grade.CLEAN
    assert drive.read_count >= 2


def other_game() -> Disk:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="ZEL"))
    return disk


def test_a_write_that_does_not_stick_fails_verification() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(writes_do_not_stick=True))

    report = write_verified(
        drive, drive, other_game(), confirm=lambda _: True, backup=None, skip_backup=True
    )

    assert not report.verified
    assert report.unchanged


def test_a_disk_left_unchanged_points_at_the_controller() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(writes_do_not_stick=True))

    report = write_verified(
        drive, drive, other_game(), confirm=lambda _: True, backup=None, skip_backup=True
    )

    assert any("FD3206" in note for note in report.notes)


def test_a_write_of_the_same_contents_is_not_mistaken_for_a_refusal() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(writes_do_not_stick=True))

    report = write_verified(
        drive, drive, sample_disk(), confirm=lambda _: True, backup=None, skip_backup=True
    )

    assert report.verified
    assert not report.unchanged


def test_a_verified_write_carries_the_portability_caveat() -> None:
    drive = SimulatedDrive(sample_disk())

    report = write_verified(drive, drive, other_game(), confirm=lambda _: True, backup=None)

    assert report.verified
    assert any("second drive" in note for note in report.notes)


def test_a_write_that_changed_the_disk_wrongly_is_not_blamed_on_the_controller() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(unstable_blocks=frozenset({1})))

    report = write_verified(drive, drive, sample_disk(), confirm=lambda _: True, backup=None)

    assert not report.verified
    assert not report.unchanged
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


def test_a_retry_that_returns_fewer_blocks_stops_the_walk() -> None:
    class ShrinkingDrive(SimulatedDrive):
        def __init__(self) -> None:
            super().__init__(sample_disk(), plan=FaultPlan(bad_crc_blocks=frozenset({1})))
            self._calls = 0

        def read_side(self, side: int):  # noqa: ANN202
            self._calls += 1
            blocks = list(super().read_side(side))
            if self._calls > 1:
                return iter(blocks[:1])
            return iter(blocks)

    result = dump(ShrinkingDrive(), sides=1, retries=3)

    assert result.sides[0].failed_blocks == (1,)


def test_a_fault_during_the_write_stops_the_run() -> None:
    class RefusingDrive(SimulatedDrive):
        def write_side(self, side: int, blocks: object) -> None:
            del side, blocks
            message = "the drive stopped answering"
            raise HardwareFaultError(message, kind=FaultKind.LINK)

    drive = RefusingDrive(sample_disk())

    with pytest.raises(WriteRefusedError, match="the write stopped at side 0"):
        write_verified(drive, drive, sample_disk(), confirm=lambda _: True, backup=None)


def test_a_read_that_overruns_its_deadline_is_a_timeout() -> None:
    class SlowDrive(SimulatedDrive):
        def read_side(self, side: int):  # noqa: ANN202
            blocks = list(super().read_side(side))
            time.sleep(0.02)
            return iter(blocks)

    with pytest.raises(HardwareFaultError) as caught:
        dump(SlowDrive(sample_disk()), sides=1, timeout=0.001)

    assert caught.value.kind is FaultKind.TIMEOUT


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
