from __future__ import annotations

from typing import Final

import pytest
from drive_double import FaultPlan, SimulatedDrive
from fakes import game_name, seeded

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs import fds
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Disk
from fdstoolkit.core.files import extract_files
from fdstoolkit.edit.disk_saves import SaveBackupError
from fdstoolkit.edit.files import FileSpec, insert_file
from fdstoolkit.hardware.disk_save import back_up_save, read_clean_side, restore_save
from fdstoolkit.hardware.session import WriteRefusedError

FAKE = seeded(__name__)
GAME = game_name(FAKE)
SAVE: Final = "SAVEDATA"
PLAYED: Final = bytes(range(64))
FRESH: Final = bytes(64)


def _game(save: bytes) -> Disk:
    disk, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True, game_name=GAME))
    for name in ("MAIN", SAVE):
        data = save if name == SAVE else bytes([0xAA]) * 32
        disk = insert_file(
            disk, side=0, spec=FileSpec(name=name, address=0x6000, kind=FileKind.PROGRAM, data=data)
        )
    return disk


def _yes(message: str) -> bool:
    del message
    return True


def test_a_save_is_backed_up_from_the_disk_in_the_drive() -> None:
    # Arrange
    drive = SimulatedDrive(_game(PLAYED))

    # Act
    backup = back_up_save(drive, side=0, number=None, retries=0)

    # Assert
    assert backup.data == PLAYED
    assert drive.write_count == 0


def test_a_side_that_does_not_read_clean_is_not_used() -> None:
    # Arrange
    drive = SimulatedDrive(_game(PLAYED), plan=FaultPlan(bad_crc_blocks=frozenset({3})))

    # Act
    with pytest.raises(WriteRefusedError) as raised:
        read_clean_side(drive, 0, 0)

    # Assert
    assert str(raised.value) == (
        "side 0 did not read clean, blocks 3 never read, so it cannot carry a save; "
        "clean the disk and try again, or rescue it first"
    )


def test_a_restore_swaps_the_save_back_and_reads_it_back() -> None:
    # Arrange
    backup = back_up_save(SimulatedDrive(_game(PLAYED)), side=0, number=None, retries=0)
    drive = SimulatedDrive(_game(FRESH))
    kept: list[bytes] = []

    # Act
    written = restore_save(drive, backup, retries=0, confirm=_yes, keep=kept.append)

    # Assert
    assert written.mismatched == ()
    assert drive.disk is not None
    files = {entry.name: entry.data for entry in extract_files(drive.disk)}
    assert files[SAVE] == PLAYED
    restored_from, _ = fds.decode(kept[0])
    assert {entry.name: entry.data for entry in extract_files(restored_from)}[SAVE] == FRESH


def test_a_declined_restore_writes_nothing() -> None:
    # Arrange
    backup = back_up_save(SimulatedDrive(_game(PLAYED)), side=0, number=None, retries=0)
    drive = SimulatedDrive(_game(FRESH))

    # Act
    with pytest.raises(WriteRefusedError) as raised:
        restore_save(drive, backup, retries=0, confirm=lambda _: False, keep=lambda _: None)

    # Assert
    assert str(raised.value) == "the operator declined the write"
    assert drive.write_count == 0


def test_a_restore_onto_another_game_writes_nothing() -> None:
    # Arrange
    backup = back_up_save(SimulatedDrive(_game(PLAYED)), side=0, number=None, retries=0)
    other, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True, game_name="ZZZ"))
    drive = SimulatedDrive(other)

    # Act
    with pytest.raises(SaveBackupError) as raised:
        restore_save(drive, backup, retries=0, confirm=_yes, keep=lambda _: None)

    # Assert
    assert str(raised.value).startswith(f"the save is from {GAME}")
    assert drive.write_count == 0


def test_a_protected_disk_is_refused_before_anything_is_read() -> None:
    # Arrange
    backup = back_up_save(SimulatedDrive(_game(PLAYED)), side=0, number=None, retries=0)
    drive = SimulatedDrive(_game(FRESH), write_protected=True)

    # Act
    with pytest.raises(WriteRefusedError) as raised:
        restore_save(drive, backup, retries=0, confirm=_yes, keep=lambda _: None)

    # Assert
    assert str(raised.value) == "cannot write: disk is write protected"
    assert drive.read_count == 0
