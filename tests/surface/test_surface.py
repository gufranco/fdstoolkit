from __future__ import annotations

from collections.abc import Sequence

import pytest
from drive_double import FaultPlan, SimulatedDrive
from surface_kit import scratch_disk

from fdstoolkit.build.calibration import LARGEST_FACTORY_SIDE, SIDE_PAYLOAD, calibration_disk
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


def test_a_healthy_disk_passes_every_pattern() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk())

    # Act
    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    # Assert
    assert report.grade is Grade.CLEAN
    assert len(report.passes) == len(PATTERNS)
    assert report.failed_patterns == ()


def test_old_blocks_past_a_short_pattern_are_not_surface_damage() -> None:
    # Arrange
    class LeftoverDrive(SimulatedDrive):
        def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
            kept = [block.payload for block in self._side(side).blocks[len(blocks) :]]
            super().write_side(side, [*blocks, *kept])

    drive = LeftoverDrive(calibration_disk(1))

    # Act
    report = surface_test(
        drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(fill=False)
    )

    # Assert
    assert report.stopped is None
    assert report.failed_patterns == ()
    assert len(report.passes) == len(PATTERNS)


def test_a_disk_that_does_not_take_a_write_stops_at_the_first_pattern() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk(), plan=FaultPlan(writes_do_not_stick=True))

    # Act
    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    # Assert
    assert report.stopped is StopReason.REFUSED
    assert report.passes == ()
    assert report.grade is Grade.FAILED
    assert drive.write_count == 1
    assert not report.passed


def test_a_block_failing_on_two_patterns_stops_the_test() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk(), plan=FaultPlan(unstable_blocks=frozenset({1})))

    # Act
    report = surface_test(drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(rounds=3))

    # Assert
    assert report.stopped is StopReason.DAMAGED
    assert len(report.passes) == 2
    assert report.hard_blocks == ((0, 1),)
    assert drive.write_count == 2


def test_a_block_failing_once_does_not_stop_the_test() -> None:
    # Arrange
    class OnceUnstableDrive(SimulatedDrive):
        def read_side(self, side: int):  # noqa: ANN202
            if self.read_count == 1:
                self._plan = FaultPlan(unstable_blocks=frozenset({1}))
            elif self.read_count == 2:
                self._plan = FaultPlan()
            return super().read_side(side)

    drive = OnceUnstableDrive(scratch_disk())

    # Act
    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    # Assert
    assert report.stopped is None
    assert len(report.passes) == len(PATTERNS)


def test_a_stopped_test_skips_its_finish() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk(), plan=FaultPlan(unstable_blocks=frozenset({1})))

    # Act
    report = surface_test(
        drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(finish=Finish.BLANK)
    )

    # Assert
    assert report.stopped is StopReason.DAMAGED
    assert not report.finish_ran
    assert drive.write_count == 2


def test_a_stop_reason_says_what_it_means() -> None:
    # Arrange
    reasons = (StopReason.DAMAGED, StopReason.REFUSED)

    # Act
    damaged, refused = (reason.value for reason in reasons)

    # Assert
    assert "damaged" in damaged
    assert "did not take a write" in refused


def test_the_test_refuses_to_run_without_consent() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk())

    # Act
    with pytest.raises(SurfaceTestRefusedError, match="declined") as raised:
        surface_test(drive, drive, sides=1, confirm=lambda _: False)

    # Assert
    assert raised.type is SurfaceTestRefusedError
    assert drive.write_count == 0


def test_the_warning_names_what_the_test_destroys() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk())
    seen: list[str] = []

    # Act
    surface_test(drive, drive, sides=1, confirm=lambda message: bool(seen.append(message)) or True)

    # Assert
    assert "destroys" in seen[0]
    assert "scratch" in seen[0]


def test_the_original_is_dumped_before_the_first_write() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk())
    saved: list[bytes] = []

    # Act
    surface_test(drive, drive, sides=1, confirm=lambda _: True, backup=saved.append)

    # Assert
    assert len(saved) == 1
    assert saved[0][:1] == bytes([0x01])


def test_the_backup_reuses_the_read_taken_before_the_first_write() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk())

    # Act
    surface_test(drive, drive, sides=1, confirm=lambda _: True, backup=lambda _: None)

    # Assert
    assert drive.read_count == 2 * len(PATTERNS)


def test_a_write_protected_disk_is_refused() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk(), write_protected=True)

    # Act
    with pytest.raises(SurfaceTestRefusedError, match="write protected") as raised:
        surface_test(drive, drive, sides=1, confirm=lambda _: True)

    # Assert
    assert raised.type is SurfaceTestRefusedError


def test_an_empty_drive_is_refused() -> None:
    # Arrange
    drive = SimulatedDrive(None)

    # Act
    with pytest.raises(SurfaceTestRefusedError, match="no disk") as raised:
        surface_test(drive, drive, sides=1, confirm=lambda _: True)

    # Assert
    assert raised.type is SurfaceTestRefusedError


def test_the_report_names_the_pattern_that_failed() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk(), plan=FaultPlan(unstable_blocks=frozenset({1})))

    # Act
    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    # Assert
    assert report.passes[0].pattern == PATTERNS[0]
    assert not report.passes[0].verified


def test_a_run_passes_only_when_every_pattern_held_and_the_finish_verified() -> None:
    # Arrange
    held = PatternPass(SurfacePattern.SHORT, verified=True, mismatched_blocks=(), grade=Grade.CLEAN)
    failed = PatternPass(
        SurfacePattern.LONG, verified=False, mismatched_blocks=((0, 3),), grade=Grade.FAILED
    )
    clean = SurfaceReport(passes=(held,))
    broken = SurfaceReport(passes=(held, failed))

    # Act
    unfinished = SurfaceReport(passes=(held,), finish_verified=False)

    # Assert
    assert clean.passed
    assert not broken.passed
    assert not unfinished.passed


def test_a_report_of_marginal_passes_is_not_clean() -> None:
    # Arrange
    passes = (
        PatternPass(
            pattern=SurfacePattern.SHORT,
            verified=True,
            mismatched_blocks=(),
            grade=Grade.MARGINAL,
        ),
    )

    # Act
    report = SurfaceReport(passes=passes)

    # Assert
    assert report.grade is Grade.MARGINAL


def test_a_report_with_an_unstable_pass_is_unstable() -> None:
    # Arrange
    passes = (
        PatternPass(
            pattern=SurfacePattern.SHORT,
            verified=True,
            mismatched_blocks=(),
            grade=Grade.UNSTABLE,
        ),
    )

    # Act
    report = SurfaceReport(passes=passes)

    # Assert
    assert report.grade is Grade.UNSTABLE


def test_a_filled_side_carries_what_factory_disks_carry_and_no_more() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk())

    # Act
    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    # Assert
    assert report.data_bytes == SIDE_PAYLOAD
    assert report.coverage == pytest.approx(SIDE_PAYLOAD / LARGEST_FACTORY_SIDE)


def test_a_quick_run_sweeps_only_a_corner_of_the_track() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk())

    # Act
    report = surface_test(
        drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(fill=False)
    )

    # Assert
    assert report.coverage < 0.2
    assert report.data_bytes < 5_000


def test_more_passes_run_the_cycle_more_times() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk())

    # Act
    report = surface_test(drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(rounds=3))

    # Assert
    assert len(report.passes) == len(PATTERNS) * 3
    assert {entry.round for entry in report.passes} == {1, 2, 3}


def test_a_run_of_no_passes_is_refused() -> None:
    # Arrange
    drive = SimulatedDrive(scratch_disk())

    # Act
    with pytest.raises(SurfaceTestRefusedError, match="at least one") as raised:
        surface_test(drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(rounds=0))

    # Assert
    assert raised.type is SurfaceTestRefusedError


def test_a_block_that_fails_twice_is_the_surface_itself() -> None:
    # Arrange
    passes = (
        PatternPass(
            SurfacePattern.SHORT,
            verified=False,
            mismatched_blocks=((0, 4),),
            grade=Grade.FAILED,
        ),
        PatternPass(
            SurfacePattern.LONG, verified=False, mismatched_blocks=((0, 4),), grade=Grade.FAILED
        ),
    )

    # Act
    report = SurfaceReport(passes=passes)

    # Assert
    assert report.hard_blocks == ((0, 4),)
    assert report.transient_blocks == ()


def test_a_block_that_fails_once_is_only_marginal() -> None:
    # Arrange
    passes = (
        PatternPass(
            SurfacePattern.SHORT,
            verified=False,
            mismatched_blocks=((0, 4),),
            grade=Grade.FAILED,
        ),
        PatternPass(SurfacePattern.LONG, verified=True, mismatched_blocks=(), grade=Grade.CLEAN),
    )

    # Act
    report = SurfaceReport(passes=passes)

    # Assert
    assert report.transient_blocks == ((0, 4),)
    assert report.hard_blocks == ()


def test_a_block_clean_after_an_early_failure_was_refreshed_by_the_rewrite() -> None:
    # Arrange
    passes = (
        PatternPass(
            SurfacePattern.SHORT,
            verified=False,
            mismatched_blocks=((0, 9),),
            grade=Grade.FAILED,
        ),
        PatternPass(SurfacePattern.LONG, verified=True, mismatched_blocks=(), grade=Grade.CLEAN),
    )

    # Act
    report = SurfaceReport(passes=passes)

    # Assert
    assert report.recovered_blocks == ((0, 9),)


def test_a_block_still_failing_on_the_last_pass_did_not_recover() -> None:
    # Arrange
    passes = (
        PatternPass(
            SurfacePattern.SHORT,
            verified=False,
            mismatched_blocks=((0, 9),),
            grade=Grade.FAILED,
        ),
        PatternPass(
            SurfacePattern.LONG, verified=False, mismatched_blocks=((0, 9),), grade=Grade.FAILED
        ),
    )

    # Act
    report = SurfaceReport(passes=passes)

    # Assert
    assert report.recovered_blocks == ()
