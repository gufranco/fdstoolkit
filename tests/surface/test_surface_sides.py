from __future__ import annotations

from collections.abc import Sequence

import pytest
from drive_double import FacingDrive, FaultPlan, SimulatedDrive
from surface_kit import (
    BLANK_BLOCKS,
    KEY,
    FinishNoisyDrive,
    HeaderLockedDrive,
    StopsAfterReads,
    failing,
    scratch_disk,
    two_sided_scratch,
)

from fdstoolkit.codecs.fds import decode
from fdstoolkit.drive.sampling import SpeedReading
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError
from fdstoolkit.hardware.session import Grade
from fdstoolkit.quality.surface import (
    Finish,
    PatternPass,
    StopReason,
    SurfacePlan,
    SurfaceReport,
    SurfaceTestRefusedError,
    surface_test,
)
from fdstoolkit.quality.surface_disks import PATTERNS, SurfacePattern


def test_a_second_side_that_was_not_turned_over_stops_the_test_and_keeps_side_a() -> None:
    # Arrange
    drive = FacingDrive(two_sided_scratch())

    # Act
    report = surface_test(drive, drive, sides=2, confirm=lambda _: True, flip=lambda _: True)

    # Assert
    assert report.stopped is StopReason.UNTURNED
    assert "not turned over" in report.refusal
    assert len(report.passes) == len(PATTERNS)
    assert drive.write_count == len(PATTERNS)


def test_a_two_side_test_with_nobody_to_turn_the_disk_is_refused_before_writing() -> None:
    # Arrange
    drive = FacingDrive(two_sided_scratch())

    # Act
    with pytest.raises(SurfaceTestRefusedError, match="turned over") as raised:
        surface_test(drive, drive, sides=2, confirm=lambda _: True)

    # Assert
    assert raised.type is SurfaceTestRefusedError
    assert drive.write_count == 0


def test_a_two_side_backup_holds_both_faces() -> None:
    # Arrange
    drive = FacingDrive(two_sided_scratch())
    saved: list[bytes] = []

    # Act
    surface_test(
        drive, drive, sides=2, confirm=lambda _: True, flip=drive.turn, backup=saved.append
    )

    # Assert
    assert decode(saved[-1])[0].side_count == 2


def test_a_surface_test_reports_each_pattern_as_it_starts() -> None:
    # Arrange
    drive = FacingDrive(two_sided_scratch())
    steps: list[str] = []

    # Act
    surface_test(
        drive, drive, sides=2, confirm=lambda _: True, flip=drive.turn, progress=steps.append
    )

    # Assert
    assert steps == [
        f"side {side} pass 1 pattern {pattern}" for side in (0, 1) for pattern in PATTERNS
    ]


def test_a_surface_finish_reports_each_side_it_finishes() -> None:
    # Arrange
    drive = FacingDrive(two_sided_scratch())
    steps: list[str] = []

    # Act
    surface_test(
        drive,
        drive,
        sides=2,
        confirm=lambda _: True,
        flip=drive.turn,
        progress=steps.append,
        plan=SurfacePlan(finish=Finish.BLANK),
    )

    # Assert
    assert steps[-2:] == ["finishing side 1", "finishing side 0"]


def test_a_finish_that_reads_back_wrong_is_reported() -> None:
    # Arrange
    drive = FinishNoisyDrive(scratch_disk())

    # Act
    report = surface_test(
        drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(finish=Finish.BLANK)
    )

    # Assert
    assert report.stopped is None
    assert report.finish_ran
    assert not report.finish_verified


@pytest.mark.parametrize(
    ("short", "long", "reading"),
    [(40, 2, SpeedReading.FAST), (1, 40, SpeedReading.SLOW), (20, 20, SpeedReading.ERRORS)],
)
def test_the_misreads_of_failed_blocks_say_whether_the_drive_or_the_surface_is_at_fault(
    short: int, long: int, reading: SpeedReading
) -> None:
    # Arrange
    verified = False
    mismatched_blocks = ((0, 3),)
    compared = 500

    # Act
    failed = PatternPass(
        SurfacePattern.LONG,
        verified=verified,
        mismatched_blocks=mismatched_blocks,
        grade=Grade.FAILED,
        short=short,
        long=long,
        compared=compared,
    )

    # Assert
    assert SurfaceReport(passes=(failed,)).pulse_reading is reading


def test_a_report_with_nothing_compared_has_no_pulse_reading() -> None:
    # Arrange
    verified = True
    mismatched_blocks = ()

    # Act
    held = PatternPass(
        SurfacePattern.SHORT,
        verified=verified,
        mismatched_blocks=mismatched_blocks,
        grade=Grade.CLEAN,
    )

    # Assert
    assert SurfaceReport(passes=(held,)).pulse_reading is None


def test_a_failed_pass_counts_the_misread_pulses_from_the_capture() -> None:
    # Arrange
    fault = FaultPlan(bad_crc_blocks=frozenset({3}), unstable_blocks=frozenset({3}))
    drive = SimulatedDrive(scratch_disk(), plan=fault)

    # Act
    report = surface_test(drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(key=KEY))

    # Assert
    failed = [entry for entry in report.passes if not entry.verified]
    assert failed
    assert all(entry.compared > 0 for entry in failed)
    assert report.pulse_reading is not None


def test_a_drive_that_keeps_the_nintendo_header_stops_the_test_with_the_reason() -> None:
    # Arrange
    drive = HeaderLockedDrive(scratch_disk())

    # Act
    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    # Assert
    assert report.stopped is StopReason.REFUSED
    assert "FMD-POWER" in report.refusal


def test_an_interrupted_test_keeps_the_passes_it_finished() -> None:
    # Arrange
    drive = StopsAfterReads(scratch_disk(), reads=4, stop=KeyboardInterrupt())

    # Act
    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    # Assert
    assert report.stopped is StopReason.INTERRUPTED
    assert len(report.passes) == 2
    assert report.grade is Grade.FAILED


def test_a_drive_that_stops_answering_keeps_the_passes_it_finished() -> None:
    # Arrange
    fault = HardwareFaultError("the device stopped answering", kind=FaultKind.LINK)
    drive = StopsAfterReads(scratch_disk(), reads=4, stop=fault)

    # Act
    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    # Assert
    assert report.stopped is StopReason.FAULT
    assert report.refusal == "the device stopped answering"
    assert len(report.passes) == 2


def test_failures_at_the_end_of_the_side_point_at_wear() -> None:
    # Arrange
    report = failing((11, 13), 14)

    # Act
    hint = report.wear_hint

    # Assert
    assert "last third of the side" in hint


def test_a_single_failing_block_points_at_one_spot() -> None:
    # Arrange
    report = failing((5,), 14)

    # Act
    hint = report.wear_hint

    # Assert
    assert "one spot" in hint


def test_failures_across_the_side_are_called_spread() -> None:
    # Arrange
    report = failing((2, 12), 14)

    # Act
    hint = report.wear_hint

    # Assert
    assert "spread across the side" in hint


def test_a_clean_run_has_no_wear_hint_and_no_cleaning_advice() -> None:
    # Arrange
    expected = ""

    # Act
    report = failing((), 14)

    # Assert
    assert report.wear_hint == expected
    assert report.advice == ""


def test_a_failed_run_suggests_cleaning_before_calling_the_disk_damaged() -> None:
    # Arrange
    report = failing((5,), 14)

    # Act
    advice = report.advice

    # Assert
    assert "clean the disk" in advice


def test_a_block_that_failed_on_side_a_is_not_recovered_by_side_b() -> None:
    # Arrange
    passes = (
        PatternPass(
            SurfacePattern.SHORT,
            verified=False,
            mismatched_blocks=((0, 4),),
            grade=Grade.FAILED,
            side=0,
        ),
        PatternPass(
            SurfacePattern.LONG, verified=True, mismatched_blocks=(), grade=Grade.CLEAN, side=1
        ),
    )

    # Act
    report = SurfaceReport(
        passes=passes,
    )

    # Assert
    assert report.recovered_blocks == ()


def test_a_block_that_failed_early_and_held_later_on_its_side_is_recovered() -> None:
    # Arrange
    passes = (
        PatternPass(
            SurfacePattern.SHORT,
            verified=False,
            mismatched_blocks=((0, 4),),
            grade=Grade.FAILED,
            side=0,
        ),
        PatternPass(
            SurfacePattern.LONG, verified=True, mismatched_blocks=(), grade=Grade.CLEAN, side=0
        ),
    )

    # Act
    report = SurfaceReport(
        passes=passes,
    )

    # Assert
    assert report.recovered_blocks == ((0, 4),)


def test_a_fault_during_the_finish_keeps_every_pass_and_says_why() -> None:
    # Arrange
    class FinishFault(SimulatedDrive):
        def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
            if len(blocks) == BLANK_BLOCKS:
                message = "the device stopped answering"
                raise HardwareFaultError(message, kind=FaultKind.LINK)
            super().write_side(side, blocks)

    drive = FinishFault(scratch_disk())

    # Act
    report = surface_test(
        drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(finish=Finish.BLANK)
    )

    # Assert
    assert len(report.passes) == len(PATTERNS)
    assert not report.finish_verified
    assert "the device stopped answering" in report.finish_problem


def test_an_interrupt_during_the_finish_says_the_side_may_be_half_written() -> None:
    # Arrange
    class FinishInterrupt(SimulatedDrive):
        def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
            if len(blocks) == BLANK_BLOCKS:
                raise KeyboardInterrupt
            super().write_side(side, blocks)

    drive = FinishInterrupt(scratch_disk())

    # Act
    report = surface_test(
        drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(finish=Finish.BLANK)
    )

    # Assert
    assert "may be half written" in report.finish_problem


def test_a_stop_before_the_first_write_leaves_the_disk_as_it_was() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk())

    # Act
    report = surface_test(
        drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(stopped=lambda: True)
    )

    # Assert
    assert report.stopped is StopReason.UNTOUCHED
    assert drive.write_count == 0


def test_a_fault_during_a_pattern_write_keeps_the_passes_before_it() -> None:
    # Arrange
    class PatternFault(SimulatedDrive):
        def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
            if self.write_count == 1:
                message = "the device stopped answering"
                raise HardwareFaultError(message, kind=FaultKind.LINK)
            super().write_side(side, blocks)

    drive = PatternFault(scratch_disk())

    # Act
    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    # Assert
    assert report.stopped is StopReason.FAULT
    assert len(report.passes) == 1
    assert "the device stopped answering" in report.refusal
