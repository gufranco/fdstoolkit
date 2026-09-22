from __future__ import annotations

import pytest

from fdstk.build.blank import blank_image
from fdstk.codecs.fds import decode
from fdstk.hardware.session import Grade
from fdstk.hardware.simulation import FaultPlan, SimulatedDrive
from fdstk.quality.surface import (
    PATTERNS,
    PatternPass,
    SurfaceReport,
    SurfaceTestRefusedError,
    surface_test,
)


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


def test_a_disk_that_does_not_hold_a_write_fails() -> None:
    drive = SimulatedDrive(scratch_disk(), plan=FaultPlan(writes_do_not_stick=True))

    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    assert report.grade is Grade.FAILED
    assert report.failed_patterns


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

    assert saved
    assert saved[0][:1] == bytes([0x01])


def test_a_write_protected_disk_is_refused() -> None:
    drive = SimulatedDrive(scratch_disk(), write_protected=True)

    with pytest.raises(SurfaceTestRefusedError, match="write protected"):
        surface_test(drive, drive, sides=1, confirm=lambda _: True)


def test_an_empty_drive_is_refused() -> None:
    drive = SimulatedDrive(None)

    with pytest.raises(SurfaceTestRefusedError, match="no disk"):
        surface_test(drive, drive, sides=1, confirm=lambda _: True)


def test_the_report_names_the_pattern_that_failed() -> None:
    drive = SimulatedDrive(scratch_disk(), plan=FaultPlan(writes_do_not_stick=True))

    report = surface_test(drive, drive, sides=1, confirm=lambda _: True)

    assert report.passes[0].pattern in PATTERNS
    assert not report.passes[0].verified


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
