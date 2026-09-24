from __future__ import annotations

from collections.abc import Sequence

import pytest
from drive_double import FaultPlan, SimulatedDrive

from fdstoolkit.build.blank import blank_image, formatted_side
from fdstoolkit.codecs.fds import decode, encode
from fdstoolkit.hardware.session import Grade
from fdstoolkit.quality.surface import (
    PATTERNS,
    Finish,
    PatternPass,
    StopReason,
    SurfacePlan,
    SurfaceReport,
    SurfaceTestRefusedError,
    blank_disk,
    surface_test,
)

BLANK_BLOCKS = 2


class FinishRefusingDrive(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        if self.write_count >= len(PATTERNS):
            self.write_count += 1
            return
        super().write_side(side, blocks)


def scratch_disk():  # noqa: ANN201
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    return disk


def test_the_patterns_are_complementary_so_a_stuck_bit_shows() -> None:
    assert 0x00 in PATTERNS
    assert 0xFF in PATTERNS
    assert 0xAA in PATTERNS
    assert 0x55 in PATTERNS


def test_a_healthy_disk_passes_every_pattern() -> None:
    drive = SimulatedDrive(scratch_disk())

    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    assert report.grade is Grade.CLEAN
    assert len(report.passes) == len(PATTERNS)
    assert report.failed_patterns == ()


def test_a_disk_that_does_not_take_a_write_stops_at_the_first_pattern() -> None:
    drive = SimulatedDrive(scratch_disk(), plan=FaultPlan(writes_do_not_stick=True))

    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    assert report.stopped is StopReason.REFUSED
    assert report.passes == ()
    assert report.grade is Grade.FAILED
    assert drive.write_count == 1
    assert not report.passed


def test_a_block_failing_on_two_patterns_stops_the_test() -> None:
    drive = SimulatedDrive(scratch_disk(), plan=FaultPlan(unstable_blocks=frozenset({1})))

    report = surface_test(drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(rounds=3))

    assert report.stopped is StopReason.DAMAGED
    assert len(report.passes) == 2
    assert report.hard_blocks == ((0, 1),)
    assert drive.write_count == 2


def test_a_block_failing_once_does_not_stop_the_test() -> None:
    class OnceUnstableDrive(SimulatedDrive):
        def read_side(self, side: int):  # noqa: ANN202
            if self.read_count == 1:
                self._plan = FaultPlan(unstable_blocks=frozenset({1}))
            elif self.read_count == 2:
                self._plan = FaultPlan()
            return super().read_side(side)

    drive = OnceUnstableDrive(scratch_disk())

    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    assert report.stopped is None
    assert len(report.passes) == len(PATTERNS)


def test_a_stopped_test_skips_its_finish() -> None:
    drive = SimulatedDrive(scratch_disk(), plan=FaultPlan(unstable_blocks=frozenset({1})))

    report = surface_test(
        drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(finish=Finish.BLANK)
    )

    assert report.stopped is StopReason.DAMAGED
    assert not report.finish_ran
    assert drive.write_count == 2


def test_a_stop_reason_says_what_it_means() -> None:
    assert "damaged" in StopReason.DAMAGED.value
    assert "did not take a write" in StopReason.REFUSED.value


def test_the_test_refuses_to_run_without_consent() -> None:
    drive = SimulatedDrive(scratch_disk())

    with pytest.raises(SurfaceTestRefusedError, match="declined"):
        surface_test(drive, drive, sides=1, confirm=lambda _: False)

    assert drive.write_count == 0


def test_the_warning_names_what_the_test_destroys() -> None:
    drive = SimulatedDrive(scratch_disk())
    seen: list[str] = []

    surface_test(drive, drive, sides=1, confirm=lambda message: bool(seen.append(message)) or True)

    assert "destroys" in seen[0]
    assert "scratch" in seen[0]


def test_the_original_is_dumped_before_the_first_write() -> None:
    drive = SimulatedDrive(scratch_disk())
    saved: list[bytes] = []

    surface_test(drive, drive, sides=1, confirm=lambda _: True, backup=saved.append)

    assert len(saved) == 1
    assert saved[0][:1] == bytes([0x01])


def test_the_backup_reuses_the_read_taken_before_the_first_write() -> None:
    drive = SimulatedDrive(scratch_disk())

    surface_test(drive, drive, sides=1, confirm=lambda _: True, backup=lambda _: None)

    assert drive.read_count == 2 * len(PATTERNS)


def test_a_write_protected_disk_is_refused() -> None:
    drive = SimulatedDrive(scratch_disk(), write_protected=True)

    with pytest.raises(SurfaceTestRefusedError, match="write protected"):
        surface_test(drive, drive, sides=1, confirm=lambda _: True)


def test_an_empty_drive_is_refused() -> None:
    drive = SimulatedDrive(None)

    with pytest.raises(SurfaceTestRefusedError, match="no disk"):
        surface_test(drive, drive, sides=1, confirm=lambda _: True)


def test_the_report_names_the_pattern_that_failed() -> None:
    drive = SimulatedDrive(scratch_disk(), plan=FaultPlan(unstable_blocks=frozenset({1})))

    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    assert report.passes[0].pattern == PATTERNS[0]
    assert not report.passes[0].verified


def test_a_run_passes_only_when_every_pattern_held_and_the_finish_verified() -> None:
    held = PatternPass(0x00, verified=True, mismatched_blocks=(), grade=Grade.CLEAN)
    failed = PatternPass(0xFF, verified=False, mismatched_blocks=((0, 3),), grade=Grade.FAILED)

    clean = SurfaceReport(passes=(held,))
    broken = SurfaceReport(passes=(held, failed))
    unfinished = SurfaceReport(passes=(held,), finish_verified=False)

    assert clean.passed
    assert not broken.passed
    assert not unfinished.passed


def test_a_report_of_marginal_passes_is_not_clean() -> None:
    report = SurfaceReport(
        passes=(
            PatternPass(pattern=0x00, verified=True, mismatched_blocks=(), grade=Grade.MARGINAL),
        )
    )

    assert report.grade is Grade.MARGINAL


def test_a_report_with_an_unstable_pass_is_unstable() -> None:
    report = SurfaceReport(
        passes=(
            PatternPass(pattern=0x00, verified=True, mismatched_blocks=(), grade=Grade.UNSTABLE),
        )
    )

    assert report.grade is Grade.UNSTABLE


def test_a_filled_side_sweeps_the_whole_physical_track() -> None:
    drive = SimulatedDrive(scratch_disk())

    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    assert report.coverage == pytest.approx(1.0, abs=0.01)
    assert report.data_bytes > 50_000


def test_a_quick_run_sweeps_only_a_corner_of_the_track() -> None:
    drive = SimulatedDrive(scratch_disk())

    report = surface_test(
        drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(fill=False)
    )

    assert report.coverage < 0.2
    assert report.data_bytes < 5_000


def test_more_passes_run_the_cycle_more_times() -> None:
    drive = SimulatedDrive(scratch_disk())

    report = surface_test(drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(rounds=3))

    assert len(report.passes) == len(PATTERNS) * 3
    assert {entry.round for entry in report.passes} == {1, 2, 3}


def test_a_run_of_no_passes_is_refused() -> None:
    drive = SimulatedDrive(scratch_disk())

    with pytest.raises(SurfaceTestRefusedError, match="at least one"):
        surface_test(drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(rounds=0))


def test_a_block_that_fails_twice_is_the_surface_itself() -> None:
    report = SurfaceReport(
        passes=(
            PatternPass(0x00, verified=False, mismatched_blocks=((0, 4),), grade=Grade.FAILED),
            PatternPass(0xFF, verified=False, mismatched_blocks=((0, 4),), grade=Grade.FAILED),
        )
    )

    assert report.hard_blocks == ((0, 4),)
    assert report.transient_blocks == ()


def test_a_block_that_fails_once_is_only_marginal() -> None:
    report = SurfaceReport(
        passes=(
            PatternPass(0x00, verified=False, mismatched_blocks=((0, 4),), grade=Grade.FAILED),
            PatternPass(0xFF, verified=True, mismatched_blocks=(), grade=Grade.CLEAN),
        )
    )

    assert report.transient_blocks == ((0, 4),)
    assert report.hard_blocks == ()


def test_a_block_clean_after_an_early_failure_was_refreshed_by_the_rewrite() -> None:
    report = SurfaceReport(
        passes=(
            PatternPass(0x00, verified=False, mismatched_blocks=((0, 9),), grade=Grade.FAILED),
            PatternPass(0xFF, verified=True, mismatched_blocks=(), grade=Grade.CLEAN),
        )
    )

    assert report.recovered_blocks == ((0, 9),)


def test_a_block_still_failing_on_the_last_pass_did_not_recover() -> None:
    report = SurfaceReport(
        passes=(
            PatternPass(0x00, verified=False, mismatched_blocks=((0, 9),), grade=Grade.FAILED),
            PatternPass(0xFF, verified=False, mismatched_blocks=((0, 9),), grade=Grade.FAILED),
        )
    )

    assert report.recovered_blocks == ()


def test_the_default_finish_leaves_the_last_pattern_on_the_disk() -> None:
    drive = SimulatedDrive(scratch_disk())

    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    assert report.finish is Finish.LEAVE
    assert drive.disk is not None
    assert drive.disk.sides[0].blocks
    assert len(drive.disk.sides[0].blocks) > BLANK_BLOCKS


def test_a_blank_finish_leaves_the_disk_as_it_left_the_kiosk() -> None:
    drive = SimulatedDrive(scratch_disk())

    report = surface_test(
        drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(finish=Finish.BLANK)
    )

    assert report.finish_verified
    assert drive.disk is not None
    assert len(drive.disk.sides[0].blocks) == BLANK_BLOCKS


def test_a_blank_finish_matches_the_factory_side_byte_for_byte() -> None:
    disk = blank_disk(sides=1, game_name="   ")
    data, _ = encode(disk, headered=False)

    assert data == formatted_side(side=0, disk_number=0, game_name="   ")


def test_an_erase_finish_leaves_nothing_the_adapter_can_read() -> None:
    drive = SimulatedDrive(scratch_disk())

    surface_test(
        drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(finish=Finish.ERASE)
    )

    assert drive.disk is not None
    assert drive.disk.sides[0].blocks == ()


def test_a_finish_that_does_not_stick_is_reported() -> None:
    drive = FinishRefusingDrive(scratch_disk())

    report = surface_test(
        drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(finish=Finish.BLANK)
    )

    assert report.stopped is None
    assert report.finish_ran
    assert not report.finish_verified
    assert not report.passed
