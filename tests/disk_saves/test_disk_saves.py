from __future__ import annotations

from typing import Final

import pytest
from fakes import game_name, seeded

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs import fds
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.core.files import extract_files
from fdstoolkit.edit.disk_saves import (
    SaveBackupError,
    backup_bytes,
    backup_of,
    load_backup,
    restored,
)
from fdstoolkit.edit.diskinfo import apply_edits
from fdstoolkit.edit.files import FileSpec, insert_file

FAKE = seeded(__name__)
GAME = game_name(FAKE)
OTHER_GAME = game_name(FAKE)
SAVE: Final = "SAVEDATA"
PLAYED: Final = bytes(range(64))
FRESH: Final = bytes(64)


def _game(
    save: bytes = FRESH, *, name: str = GAME, files: tuple[str, ...] = ("MAIN", SAVE)
) -> Disk:
    disk, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True, game_name=name))
    for file_name in files:
        data = save if file_name == SAVE else bytes([0xAA]) * 32
        disk = insert_file(
            disk,
            side=0,
            spec=FileSpec(name=file_name, address=0x6000, kind=FileKind.PROGRAM, data=data),
        )
    return disk


def _save_number(disk: Disk) -> int:
    return next(entry.number for entry in extract_files(disk) if entry.name == SAVE)


def test_the_file_named_like_a_save_is_backed_up_with_the_game_it_belongs_to() -> None:
    # Arrange
    disk = _game(PLAYED)

    # Act
    backup = backup_of(0, disk.sides[0], None)

    # Assert
    assert (backup.side, backup.name, backup.data) == (0, SAVE, PLAYED)
    assert backup.number == _save_number(disk)
    assert backup.identity.game == GAME


def test_a_file_named_by_number_is_backed_up_whatever_its_name() -> None:
    # Arrange
    disk = _game(files=("MAIN", "PROGRESS"))
    number = next(entry.number for entry in extract_files(disk) if entry.name == "PROGRESS")

    # Act
    backup = backup_of(0, disk.sides[0], number)

    # Assert
    assert backup.name == "PROGRESS"


def test_no_file_named_like_a_save_asks_for_its_number() -> None:
    # Arrange
    disk = _game(files=("MAIN", "PROGRESS"))

    # Act
    with pytest.raises(SaveBackupError) as raised:
        backup_of(0, disk.sides[0], None)

    # Assert
    assert str(raised.value) == (
        "no file on side 0 has a name that reads like a save; pass --file with its number, "
        "which info --files lists"
    )


def test_two_files_named_like_a_save_ask_which_one() -> None:
    # Arrange
    disk = _game(files=(SAVE, "SAVE2"))

    # Act
    with pytest.raises(SaveBackupError) as raised:
        backup_of(0, disk.sides[0], None)

    # Assert
    assert str(raised.value).startswith("side 0 has more than one file named like a save:")


def test_a_number_no_file_carries_is_refused() -> None:
    # Arrange
    disk = _game()

    # Act
    with pytest.raises(SaveBackupError) as raised:
        backup_of(0, disk.sides[0], 99)

    # Assert
    assert str(raised.value) == "side 0 has no file numbered 99"


def test_a_side_with_no_disk_information_has_no_game_to_back_up() -> None:
    # Arrange
    side = Side(blocks=(), tail=b"", capacity=0)

    # Act
    with pytest.raises(SaveBackupError) as raised:
        backup_of(0, side, None)

    # Assert
    assert str(raised.value) == "side 0 carries no disk information, so its game is unknown"


def test_a_backup_reads_back_as_itself() -> None:
    # Arrange
    backup = backup_of(0, _game(PLAYED).sides[0], None)

    # Act
    loaded = load_backup(backup_bytes(backup))

    # Assert
    assert loaded == backup


@pytest.mark.parametrize(
    "data",
    [
        b"not json",
        b"[]",
        b'{"format": "other"}',
        b'{"format": "fdstoolkit-save", "version": 1, "data": 7}',
        b'{"format": "fdstoolkit-save", "version": 1, "data": "00", "identity": [1]}',
        (
            b'{"format": "fdstoolkit-save", "version": 1, "side": 0, "number": 1, "name": "S", '
            b'"data": "zz", "identity": {"licensee": 1, "game": "A", "version": 0, "disk": 0}}'
        ),
        (
            b'{"format": "fdstoolkit-save", "version": 1, "side": "0", "number": 1, "name": "S", '
            b'"data": "00", "identity": {"licensee": 1, "game": "A", "version": 0, "disk": 0}}'
        ),
        (
            b'{"format": "fdstoolkit-save", "version": 1, "side": 0, "number": 1, "name": "S", '
            b'"data": "00", "identity": {"game": "A"}}'
        ),
    ],
)
def test_a_file_that_is_not_a_save_backup_is_refused(data: bytes) -> None:
    # Arrange
    expected = "this is not a save backup that disk-save wrote"

    # Act
    with pytest.raises(SaveBackupError) as raised:
        load_backup(data)

    # Assert
    assert str(raised.value) == expected


def test_restoring_swaps_only_the_save_file() -> None:
    # Arrange
    backup = backup_of(0, _game(PLAYED).sides[0], None)
    fresh = _game(FRESH)

    # Act
    side = restored(0, fresh.sides[0], backup)

    # Assert
    files = {entry.name: entry.data for entry in extract_files(Disk(sides=(side,)))}
    assert files[SAVE] == PLAYED
    assert files["MAIN"] == bytes([0xAA]) * 32
    assert side.blocks[0] == fresh.sides[0].blocks[0]


def test_restoring_onto_another_game_is_refused_naming_both() -> None:
    # Arrange
    backup = backup_of(0, _game(PLAYED).sides[0], None)
    other = _game(name=OTHER_GAME)

    # Act
    with pytest.raises(SaveBackupError) as raised:
        restored(0, other.sides[0], backup)

    # Assert
    assert str(raised.value) == (
        f"the save is from {GAME} version 0, disk 0, and the disk in the drive is "
        f"{OTHER_GAME} version 0, disk 0; nothing was written"
    )


def test_restoring_onto_the_other_side_is_refused() -> None:
    # Arrange
    backup = backup_of(0, _game(PLAYED).sides[0], None)
    flipped, _ = apply_edits(_game(), side=0, edits={"side": 1})

    # Act
    with pytest.raises(SaveBackupError) as raised:
        restored(0, flipped.sides[0], backup)

    # Assert
    assert str(raised.value) == (
        "the disk shows side 1 face down, and the save belongs to side 0; turn the disk over"
    )


def test_restoring_a_save_of_another_size_is_refused() -> None:
    # Arrange
    backup = backup_of(0, _game(PLAYED).sides[0], None)
    shorter = _game(bytes(16))

    # Act
    with pytest.raises(SaveBackupError) as raised:
        restored(0, shorter.sides[0], backup)

    # Assert
    assert str(raised.value) == (
        f"file {backup.number} {SAVE} holds 16 bytes on the disk and 64 in the save, "
        "so it is another release; nothing was written"
    )


def test_restoring_where_the_file_is_gone_is_refused() -> None:
    # Arrange
    backup = backup_of(0, _game(PLAYED).sides[0], None)
    without = _game(files=("MAIN",))

    # Act
    with pytest.raises(SaveBackupError) as raised:
        restored(0, without.sides[0], backup)

    # Assert
    assert str(raised.value) == (
        f"side 0 has no file {backup.number} named {SAVE}, so it is another release; "
        "nothing was written"
    )


def test_restoring_onto_a_side_with_no_disk_information_is_refused() -> None:
    # Arrange
    backup = backup_of(0, _game(PLAYED).sides[0], None)

    # Act
    with pytest.raises(SaveBackupError) as raised:
        restored(0, Side(blocks=(), tail=b"", capacity=0), backup)

    # Assert
    assert str(raised.value) == "side 0 carries no disk information, so its game is unknown"
