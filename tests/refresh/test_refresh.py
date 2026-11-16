from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Final

import pytest
from capture_fixture import disk_with_a_file
from drive_double import FacingDrive, FaultPlan, SimulatedDrive
from fakes import game_name, seeded

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs import fds
from fdstoolkit.core.disk import Disk
from fdstoolkit.hardware.refresh import (
    REWIND,
    RefreshPlan,
    RefreshRefusedError,
    refresh_disk,
)
from fdstoolkit.hardware.session import SideFlipError

FAKE = seeded(__name__)
GAME = game_name(FAKE)
DAMAGED: Final = 3


class HealsOnWrite(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        super().write_side(side, blocks)
        self._plan = FaultPlan()


def _two_sides() -> Disk:
    disk, _ = fds.decode(blank_image(sides=2, headered=False, formatted=True, game_name=GAME))
    return disk


def _yes(message: str) -> bool:
    del message
    return True


def _drop(disk: Disk) -> None:
    del disk


def _plan(
    *,
    sides: int = 1,
    passes: int = 3,
    retries: int = 0,
    ask: Callable[[str], bool] = _yes,
    keep: Callable[[Disk], None] = _drop,
) -> RefreshPlan:
    return RefreshPlan(sides=sides, passes=passes, retries=retries, ask=ask, keep=keep, backup=None)


def test_a_clean_disk_is_read_rebuilt_and_written_back() -> None:
    # Arrange
    disk = disk_with_a_file()
    drive = SimulatedDrive(disk)
    kept: list[Disk] = []

    # Act
    report = refresh_disk(drive, _plan(keep=kept.append))

    # Assert
    assert report.write.verified
    assert drive.write_count == 1
    assert kept[0].sides[0].blocks[DAMAGED].payload == disk.sides[0].blocks[DAMAGED].payload


def test_a_block_the_vote_rebuilds_is_written_back_clean() -> None:
    # Arrange
    disk = disk_with_a_file()
    drive = HealsOnWrite(disk, plan=FaultPlan(bad_crc_blocks=frozenset({DAMAGED})))

    # Act
    report = refresh_disk(drive, _plan(retries=2))

    # Assert
    assert report.write.verified
    assert any("recovered" in line for line in report.lines)


def test_a_block_that_never_settled_stops_the_write() -> None:
    # Arrange
    drive = SimulatedDrive(disk_with_a_file(), plan=FaultPlan(bad_crc_blocks=frozenset({DAMAGED})))

    # Act
    with pytest.raises(RefreshRefusedError) as raised:
        refresh_disk(drive, _plan(passes=1))

    # Assert
    assert str(raised.value) == (
        f"side 0 block {DAMAGED} never read clean and the vote could not rebuild it, "
        "so nothing was written"
    )
    assert drive.write_count == 0


def test_a_two_sided_disk_is_turned_back_before_side_a_is_written() -> None:
    # Arrange
    drive = FacingDrive(_two_sides())
    asked: list[str] = []

    def operator(message: str) -> bool:
        asked.append(message)
        if "turn the disk" in message:
            drive.turn(message)
        return True

    # Act
    report = refresh_disk(drive, _plan(sides=2, passes=1, ask=operator))

    # Assert
    assert report.write.verified
    assert REWIND in asked


def test_a_declined_turn_back_writes_nothing() -> None:
    # Arrange
    drive = FacingDrive(_two_sides())

    def operator(message: str) -> bool:
        if message == REWIND:
            return False
        drive.turn(message)
        return True

    # Act
    with pytest.raises(SideFlipError) as raised:
        refresh_disk(drive, _plan(sides=2, passes=1, ask=operator))

    # Assert
    assert str(raised.value) == "the disk was not turned back to side A, so nothing was written"
    assert drive.write_count == 0


def test_a_disk_left_on_side_b_is_caught_before_writing() -> None:
    # Arrange
    drive = FacingDrive(_two_sides())

    def operator(message: str) -> bool:
        if message != REWIND:
            drive.turn(message)
        return True

    # Act
    with pytest.raises(SideFlipError) as raised:
        refresh_disk(drive, _plan(sides=2, passes=1, ask=operator))

    # Assert
    assert str(raised.value) == (
        "side A is not face down: the disk information under the head is not side A's, "
        "so nothing was written"
    )
    assert drive.write_count == 0
