from __future__ import annotations

from collections.abc import Sequence

import pytest
from drive_double import FacingDrive, FaultPlan, SimulatedDrive

from fdstoolkit.build.blank import blank_image, formatted_side
from fdstoolkit.build.calibration import LARGEST_FACTORY_SIDE, SIDE_PAYLOAD
from fdstoolkit.codecs.fds import decode, encode
from fdstoolkit.codecs.raw import class_histogram, encode_era_b
from fdstoolkit.core.blocks import BlockKind
from fdstoolkit.core.crc import block_crc, encode_crc
from fdstoolkit.drive.monitor import SpeedReading
from fdstoolkit.hardware.session import Grade, SideFlipError
from fdstoolkit.quality.surface import (
    PATTERNS,
    Finish,
    PatternPass,
    StopReason,
    SurfacePattern,
    SurfacePlan,
    SurfaceReport,
    SurfaceTestRefusedError,
    blank_disk,
    pattern_disk,
    surface_test,
)

BLANK_BLOCKS = 2
KEY = bytes(range(16))
OTHER_KEY = bytes(range(1, 17))
DOMINANT = 0.99
MIXED_SHARE = 0.1


class FinishNoisyDrive(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        super().write_side(side, blocks)
        if self.write_count > len(PATTERNS):
            self._plan = FaultPlan(unstable_blocks=frozenset({1}))


class FinishRefusingDrive(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        if self.write_count >= len(PATTERNS):
            self.write_count += 1
            return
        super().write_side(side, blocks)


def scratch_disk():  # noqa: ANN201
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    return disk


def shares(payload: bytes) -> tuple[float, float, float]:
    framed = bytes([0x80]) + payload + encode_crc(block_crc(payload))
    counts = class_histogram(encode_era_b(framed))
    total = counts[0] + counts[1] + counts[2]
    return counts[0] / total, counts[1] / total, counts[2] / total


def data_of(pattern: SurfacePattern, key: bytes = KEY) -> bytes:
    side = pattern_disk(pattern, sides=1, key=key).sides[0]
    return b"".join(b.payload for b in side.blocks if b.kind is BlockKind.FILE_DATA)


@pytest.mark.parametrize(
    ("pattern", "position"),
    [(SurfacePattern.SHORT, 0), (SurfacePattern.MEDIUM, 1), (SurfacePattern.LONG, 2)],
)
def test_each_fixed_pattern_writes_one_pulse_class(pattern: SurfacePattern, position: int) -> None:
    assert shares(data_of(pattern))[position] >= DOMINANT


def test_the_unique_pattern_writes_every_pulse_class() -> None:
    assert all(share > MIXED_SHARE for share in shares(data_of(SurfacePattern.UNIQUE)))


def test_the_unique_pattern_changes_with_its_key_and_differs_between_files() -> None:
    side = pattern_disk(SurfacePattern.UNIQUE, sides=1, key=KEY).sides[0]
    files = [b.payload for b in side.blocks if b.kind is BlockKind.FILE_DATA]

    assert len(set(files)) == len(files)
    assert data_of(SurfacePattern.UNIQUE, KEY) != data_of(SurfacePattern.UNIQUE, OTHER_KEY)


def test_every_pulse_class_is_written_in_one_pass() -> None:
    assert set(PATTERNS) == set(SurfacePattern)


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
    held = PatternPass(SurfacePattern.SHORT, verified=True, mismatched_blocks=(), grade=Grade.CLEAN)
    failed = PatternPass(
        SurfacePattern.LONG, verified=False, mismatched_blocks=((0, 3),), grade=Grade.FAILED
    )

    clean = SurfaceReport(passes=(held,))
    broken = SurfaceReport(passes=(held, failed))
    unfinished = SurfaceReport(passes=(held,), finish_verified=False)

    assert clean.passed
    assert not broken.passed
    assert not unfinished.passed


def test_a_report_of_marginal_passes_is_not_clean() -> None:
    report = SurfaceReport(
        passes=(
            PatternPass(
                pattern=SurfacePattern.SHORT,
                verified=True,
                mismatched_blocks=(),
                grade=Grade.MARGINAL,
            ),
        )
    )

    assert report.grade is Grade.MARGINAL


def test_a_report_with_an_unstable_pass_is_unstable() -> None:
    report = SurfaceReport(
        passes=(
            PatternPass(
                pattern=SurfacePattern.SHORT,
                verified=True,
                mismatched_blocks=(),
                grade=Grade.UNSTABLE,
            ),
        )
    )

    assert report.grade is Grade.UNSTABLE


def test_a_filled_side_carries_what_factory_disks_carry_and_no_more() -> None:
    drive = SimulatedDrive(scratch_disk())

    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    assert report.data_bytes == SIDE_PAYLOAD
    assert report.coverage == pytest.approx(SIDE_PAYLOAD / LARGEST_FACTORY_SIDE)


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
    )

    assert report.hard_blocks == ((0, 4),)
    assert report.transient_blocks == ()


def test_a_block_that_fails_once_is_only_marginal() -> None:
    report = SurfaceReport(
        passes=(
            PatternPass(
                SurfacePattern.SHORT,
                verified=False,
                mismatched_blocks=((0, 4),),
                grade=Grade.FAILED,
            ),
            PatternPass(
                SurfacePattern.LONG, verified=True, mismatched_blocks=(), grade=Grade.CLEAN
            ),
        )
    )

    assert report.transient_blocks == ((0, 4),)
    assert report.hard_blocks == ()


def test_a_block_clean_after_an_early_failure_was_refreshed_by_the_rewrite() -> None:
    report = SurfaceReport(
        passes=(
            PatternPass(
                SurfacePattern.SHORT,
                verified=False,
                mismatched_blocks=((0, 9),),
                grade=Grade.FAILED,
            ),
            PatternPass(
                SurfacePattern.LONG, verified=True, mismatched_blocks=(), grade=Grade.CLEAN
            ),
        )
    )

    assert report.recovered_blocks == ((0, 9),)


def test_a_block_still_failing_on_the_last_pass_did_not_recover() -> None:
    report = SurfaceReport(
        passes=(
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


def two_sided_scratch():  # noqa: ANN201
    disk, _ = decode(blank_image(sides=2, headered=False, formatted=True, game_name="SMB"))
    return disk


def test_a_two_side_surface_test_turns_the_disk_once() -> None:
    drive = FacingDrive(two_sided_scratch())

    report = surface_test(drive, drive, sides=2, confirm=lambda _: True, flip=drive.turn)

    assert drive.turns == 1
    assert len(report.passes) == 2 * len(PATTERNS)
    assert {entry.side for entry in report.passes} == {0, 1}
    assert report.passed


def test_a_two_side_blank_finish_turns_back_and_leaves_both_faces_blank() -> None:
    drive = FacingDrive(two_sided_scratch())

    report = surface_test(
        drive,
        drive,
        sides=2,
        confirm=lambda _: True,
        flip=drive.turn,
        plan=SurfacePlan(finish=Finish.BLANK),
    )

    assert report.finish_verified
    assert drive.turns == 2
    assert drive.disk is not None
    assert drive.disk.sides == blank_disk(sides=2).sides


def test_a_finish_whose_turn_was_skipped_writes_nothing_and_says_why() -> None:
    drive = FacingDrive(two_sided_scratch())
    turns = iter([True, False])

    def turn_once(message: str) -> bool:
        return drive.turn(message) if next(turns) else True

    report = surface_test(
        drive,
        drive,
        sides=2,
        confirm=lambda _: True,
        flip=turn_once,
        plan=SurfacePlan(finish=Finish.BLANK),
    )

    assert not report.finish_verified
    assert "not turned over" in report.finish_problem
    assert drive.write_count == 2 * len(PATTERNS) + 1
    assert drive.disk is not None
    assert drive.disk.sides[1] == blank_disk(sides=2).sides[1]


def test_a_second_side_that_was_not_turned_over_stops_the_test() -> None:
    drive = FacingDrive(two_sided_scratch())

    with pytest.raises(SideFlipError, match="not turned over"):
        surface_test(drive, drive, sides=2, confirm=lambda _: True, flip=lambda _: True)

    assert drive.write_count == len(PATTERNS)


def test_a_two_side_test_with_nobody_to_turn_the_disk_is_refused_before_writing() -> None:
    drive = FacingDrive(two_sided_scratch())

    with pytest.raises(SurfaceTestRefusedError, match="turned over"):
        surface_test(drive, drive, sides=2, confirm=lambda _: True)

    assert drive.write_count == 0


def test_a_two_side_backup_holds_both_faces() -> None:
    drive = FacingDrive(two_sided_scratch())
    saved: list[bytes] = []

    surface_test(
        drive, drive, sides=2, confirm=lambda _: True, flip=drive.turn, backup=saved.append
    )

    assert decode(saved[-1])[0].side_count == 2


def test_a_surface_test_reports_each_pattern_as_it_starts() -> None:
    drive = FacingDrive(two_sided_scratch())
    steps: list[str] = []

    surface_test(
        drive, drive, sides=2, confirm=lambda _: True, flip=drive.turn, progress=steps.append
    )

    assert steps == [
        f"side {side} pass 1 pattern {pattern}" for side in (0, 1) for pattern in PATTERNS
    ]


def test_a_surface_finish_reports_each_side_it_finishes() -> None:
    drive = FacingDrive(two_sided_scratch())
    steps: list[str] = []

    surface_test(
        drive,
        drive,
        sides=2,
        confirm=lambda _: True,
        flip=drive.turn,
        progress=steps.append,
        plan=SurfacePlan(finish=Finish.BLANK),
    )

    assert steps[-2:] == ["finishing side 1", "finishing side 0"]


def test_a_finish_that_reads_back_wrong_is_reported() -> None:
    drive = FinishNoisyDrive(scratch_disk())

    report = surface_test(
        drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(finish=Finish.BLANK)
    )

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
    failed = PatternPass(
        SurfacePattern.LONG,
        verified=False,
        mismatched_blocks=((0, 3),),
        grade=Grade.FAILED,
        short=short,
        long=long,
        compared=500,
    )

    assert SurfaceReport(passes=(failed,)).pulse_reading is reading


def test_a_report_with_nothing_compared_has_no_pulse_reading() -> None:
    held = PatternPass(SurfacePattern.SHORT, verified=True, mismatched_blocks=(), grade=Grade.CLEAN)

    assert SurfaceReport(passes=(held,)).pulse_reading is None


def test_a_failed_pass_counts_the_misread_pulses_from_the_capture() -> None:
    fault = FaultPlan(bad_crc_blocks=frozenset({3}), unstable_blocks=frozenset({3}))
    drive = SimulatedDrive(scratch_disk(), plan=fault)

    report = surface_test(drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(key=KEY))

    failed = [entry for entry in report.passes if not entry.verified]
    assert failed
    assert all(entry.compared > 0 for entry in failed)
    assert report.pulse_reading is not None


class HeaderLockedDrive(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        kept = self._side(side).blocks[0].payload
        super().write_side(side, [kept, *blocks[1:]])


def test_a_drive_that_keeps_the_nintendo_header_stops_the_test_with_the_reason() -> None:
    drive = HeaderLockedDrive(scratch_disk())

    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    assert report.stopped is StopReason.REFUSED
    assert "FMD-POWER" in report.refusal
