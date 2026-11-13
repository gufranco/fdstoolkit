from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest
from drive_double import FacingDrive, FaultPlan, SimulatedDrive

from fdstoolkit.build.blank import blank_image, formatted_side
from fdstoolkit.build.calibration import LARGEST_FACTORY_SIDE, SIDE_PAYLOAD, calibration_disk
from fdstoolkit.codecs.fds import decode, encode
from fdstoolkit.codecs.raw import class_histogram, encode_era_b
from fdstoolkit.core.blocks import BlockKind
from fdstoolkit.core.crc import block_crc, encode_crc
from fdstoolkit.core.disk import Disk
from fdstoolkit.drive.monitor import SpeedReading
from fdstoolkit.hardware.ports import BlockRead, FaultKind, HardwareFaultError
from fdstoolkit.hardware.session import MAX_PASSES, Grade
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
    # Arrange
    data = data_of(pattern)

    # Act
    found = shares(data)

    # Assert
    assert found[position] >= DOMINANT


def test_the_unique_pattern_writes_every_pulse_class() -> None:
    # Arrange
    data = data_of(SurfacePattern.UNIQUE)

    # Act
    found = shares(data)

    # Assert
    assert all(share > MIXED_SHARE for share in found)


def test_the_unique_pattern_changes_with_its_key_and_differs_between_files() -> None:
    # Arrange
    side = pattern_disk(SurfacePattern.UNIQUE, sides=1, key=KEY).sides[0]

    # Act
    files = [b.payload for b in side.blocks if b.kind is BlockKind.FILE_DATA]

    # Assert
    assert len(set(files)) == len(files)
    assert data_of(SurfacePattern.UNIQUE, KEY) != data_of(SurfacePattern.UNIQUE, OTHER_KEY)


def test_every_pulse_class_is_written_in_one_pass() -> None:
    # Arrange
    expected = set(SurfacePattern)

    # Act
    result = set(PATTERNS)

    # Assert
    assert result == expected


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


def two_sided_scratch():  # noqa: ANN201
    disk, _ = decode(blank_image(sides=2, headered=False, formatted=True, game_name="SMB"))
    return disk


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
    report = surface_test(drive, drive, sides=1, confirm=lambda _: True, plan=SurfacePlan(key=KEY))

    # Act
    failed = [entry for entry in report.passes if not entry.verified]

    # Assert
    assert failed
    assert all(entry.compared > 0 for entry in failed)
    assert report.pulse_reading is not None


class HeaderLockedDrive(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        kept = self._side(side).blocks[0].payload
        super().write_side(side, [kept, *blocks[1:]])


def test_a_drive_that_keeps_the_nintendo_header_stops_the_test_with_the_reason() -> None:
    # Arrange
    drive = HeaderLockedDrive(scratch_disk())

    # Act
    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    # Assert
    assert report.stopped is StopReason.REFUSED
    assert "FMD-POWER" in report.refusal


class StopsAfterReads(SimulatedDrive):
    def __init__(self, disk: Disk, *, reads: int, stop: BaseException) -> None:
        super().__init__(disk)
        self.limit = reads
        self.stop = stop

    def read_side(self, side: int) -> Iterator[BlockRead]:
        if self.read_count >= self.limit:
            raise self.stop
        return super().read_side(side)


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


def failing(blocks: tuple[int, ...], per_side: int) -> SurfaceReport:
    return SurfaceReport(
        passes=(
            PatternPass(
                SurfacePattern.SHORT,
                verified=False,
                mismatched_blocks=tuple((0, block) for block in blocks),
                grade=Grade.FAILED,
            ),
        ),
        blocks_per_side=per_side,
    )


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
