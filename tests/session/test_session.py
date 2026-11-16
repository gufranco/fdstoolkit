from __future__ import annotations

from collections.abc import Iterator

import pytest
from drive_double import FaultPlan, SimulatedDrive
from session_kit import (
    GAME,
    DroppingDrive,
    HeaderLockedDrive,
    OverlayDrive,
    ShortFirstReadDrive,
    disk_with_files,
    longer_than_any_factory_side,
    sample_disk,
)

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.calibration import calibration_disk
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.disk import SIDE_SIZE, Disk, Side
from fdstoolkit.hardware.ports import BlockRead, FaultKind, HardwareFaultError
from fdstoolkit.hardware.session import (
    Grade,
    HalfWriteError,
    LongSideError,
    WriteNotTakenError,
    WriteRefusedError,
    dump,
    dump_repeated,
)
from fdstoolkit.hardware.writing import STALE_BLOCK, refuse_long_sides, write_verified


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

    # Act
    result = dump(drive, sides=1, retries=2)

    # Assert
    recovered = result.sides[0].blocks[last_data]
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


def with_factory_info(image: Disk) -> Disk:
    info = decode(blank_image(sides=1, headered=False, formatted=True, game_name=GAME))[0]
    blocks = (info.sides[0].blocks[0], *image.sides[0].blocks[1:])
    return Disk(sides=(Side(blocks=blocks, tail=b"", capacity=SIDE_SIZE),))


def test_a_drive_that_keeps_the_nintendo_header_is_named_as_half_modified() -> None:
    # Arrange
    drive = HeaderLockedDrive(disk_with_files())
    image = with_factory_info(disk_with_files(2))

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
