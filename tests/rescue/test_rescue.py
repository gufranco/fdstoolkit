from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Final

import pytest
from capture_fixture import DAMAGED, disk_with_a_file, read_of
from fakes import game_name, seeded

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs import fds
from fdstoolkit.core.disk import Disk
from fdstoolkit.drive.captures import MANIFEST, Capture, bundle_zip
from fdstoolkit.drive.rescue import (
    EMPTY,
    STATE_NAME,
    RescueError,
    identity_problem,
    load_folder,
    load_zip,
    progress_of,
    save_folder,
    state_zip,
    with_read,
)
from fdstoolkit.hardware.ports import BlockRead

FAKE = seeded(__name__)
OTHER_GAME = game_name(FAKE)
SHARED_ERROR: Final = 10


def _blocks(disk: Disk, side: int = 0, *, bad_first: bool = False) -> tuple[BlockRead, ...]:
    return tuple(
        BlockRead(
            index=index,
            payload=block.payload,
            crc_ok=not (bad_first and index == 0),
            attempts=1,
        )
        for index, block in enumerate(disk.sides[side].blocks)
    )


def _read(disk: Disk, offset: int | None) -> Capture:
    return Capture(side=0, read=1, data=read_of(disk, offset))


def test_a_folder_that_holds_nothing_yet_is_an_empty_rescue(tmp_path: Path) -> None:
    # Arrange
    folder = tmp_path / "rescue"

    # Act
    state = load_folder(folder)

    # Assert
    assert state == EMPTY


def test_reads_are_numbered_on_from_those_already_kept() -> None:
    # Arrange
    disk = disk_with_a_file()

    # Act
    state = with_read(
        with_read(EMPTY, 0, _blocks(disk), _read(disk, None)), 0, _blocks(disk), _read(disk, None)
    )

    # Assert
    assert [capture.read for capture in state.captures] == [1, 2]
    assert state.reads_of(0) == 2
    assert state.info_of(0) == disk.sides[0].blocks[0].payload


def test_three_reads_wrong_in_the_same_place_leave_the_block_unsettled() -> None:
    # Arrange
    disk = disk_with_a_file()
    state = with_read(EMPTY, 0, _blocks(disk), _read(disk, SHARED_ERROR))
    state = with_read(state, 0, _blocks(disk), _read(disk, SHARED_ERROR))
    state = with_read(state, 0, _blocks(disk), _read(disk, SHARED_ERROR))

    # Act
    found = progress_of(state)

    # Assert
    assert not found.settled
    assert found.sides[0].unsettled == (DAMAGED,)
    assert found.lines[-1] == f"side 0: 1 block(s) unsettled after 3 read(s): {DAMAGED}"


def test_one_clean_read_on_another_day_settles_the_block() -> None:
    # Arrange
    disk = disk_with_a_file()
    state = EMPTY
    for _ in range(3):
        state = with_read(state, 0, _blocks(disk), _read(disk, SHARED_ERROR))
    state = with_read(state, 0, _blocks(disk), _read(disk, None))

    # Act
    found = progress_of(state)

    # Assert
    assert found.settled
    assert found.disk.sides[0].blocks[DAMAGED].payload == disk.sides[0].blocks[DAMAGED].payload
    assert found.lines[-1] == "side 0: every declared block settled after 4 read(s)"


def test_a_side_whose_file_count_never_read_is_not_settled() -> None:
    # Arrange
    capture = Capture(side=0, read=1, data=bytes(64))

    # Act
    found = progress_of(with_read(EMPTY, 0, (), capture))

    # Assert
    assert not found.settled
    assert (
        found.lines[-1] == "side 0: the declared file count has not read clean yet, after 1 read(s)"
    )


def test_a_rescue_survives_being_saved_and_loaded(tmp_path: Path) -> None:
    # Arrange
    disk = disk_with_a_file()
    state = with_read(EMPTY, 0, _blocks(disk), _read(disk, SHARED_ERROR))
    folder = tmp_path / "rescue"

    # Act
    save_folder(folder, state)

    # Assert
    assert load_folder(folder) == state
    assert (folder / MANIFEST).is_file()
    assert (folder / "side0.read01.raw03").read_bytes() == state.captures[0].data


def test_saving_again_keeps_the_previous_state_beside_the_new_one(tmp_path: Path) -> None:
    # Arrange
    disk = disk_with_a_file()
    folder = tmp_path / "rescue"
    first = with_read(EMPTY, 0, _blocks(disk), _read(disk, SHARED_ERROR))
    save_folder(folder, first)
    previous = (folder / MANIFEST).read_bytes()

    # Act
    save_folder(folder, with_read(first, 0, _blocks(disk), _read(disk, None)))

    # Assert
    assert (folder / f"{MANIFEST}.bak").read_bytes() == previous
    assert (folder / f"{STATE_NAME}.bak").is_file()
    assert not list(folder.glob("*.tmp"))
    assert load_folder(folder).reads_of(0) == 2


def test_a_rescue_travels_as_one_zip() -> None:
    # Arrange
    disk = disk_with_a_file()
    state = with_read(EMPTY, 0, _blocks(disk), _read(disk, None))

    # Act
    zipped = state_zip(state)

    # Assert
    assert load_zip(zipped) == state


def test_a_capture_bundle_without_a_rescue_state_starts_a_rescue_from_its_reads() -> None:
    # Arrange
    disk = disk_with_a_file()
    zipped = bundle_zip([_read(disk, None)], image="dump.fds", created="2026-11-16T17:00:00Z")

    # Act
    state = load_zip(zipped)

    # Assert
    assert state.identity is None
    assert state.reads_of(0) == 1


def test_a_zip_that_is_not_a_bundle_is_refused() -> None:
    # Arrange
    data = b"not a zip"

    # Act
    with pytest.raises(RescueError) as raised:
        load_zip(data)

    # Assert
    assert "zip" in str(raised.value)


def test_a_folder_whose_manifest_is_broken_is_refused(tmp_path: Path) -> None:
    # Arrange
    folder = tmp_path / "rescue"
    folder.mkdir()
    (folder / MANIFEST).write_text("{", encoding="utf-8")

    # Act
    with pytest.raises(RescueError) as raised:
        load_folder(folder)

    # Assert
    assert "does not parse" in str(raised.value)


@pytest.mark.parametrize(
    "state",
    [
        b"[]",
        b'{"format": "something else", "version": 1}',
        b'{"format": "fdstoolkit-rescue", "version": 2, "identity": null, "sides": {}}',
        b'{"format": "fdstoolkit-rescue", "version": 1, "identity": null, "sides": []}',
        b'{"format": "fdstoolkit-rescue", "version": 1, "identity": null, "sides": {"x": "00"}}',
        b'{"format": "fdstoolkit-rescue", "version": 1, "identity": null, "sides": {"0": "zz"}}',
        b'{"format": "fdstoolkit-rescue", "version": 1, "identity": {"game": 1}, "sides": {}}',
        (
            b'{"format": "fdstoolkit-rescue", "version": 1, "sides": {}, "identity": '
            b'{"licensee": 1, "game": 2, "version": 0, "disk": 0}}'
        ),
        (
            b'{"format": "fdstoolkit-rescue", "version": 1, "sides": {}, "identity": '
            b'{"licensee": 1, "game": "ZEL", "version": "0", "disk": 0}}'
        ),
        b"not json",
    ],
)
def test_a_rescue_state_that_is_not_one_is_refused(tmp_path: Path, state: bytes) -> None:
    # Arrange
    disk = disk_with_a_file()
    folder = tmp_path / "rescue"
    save_folder(folder, with_read(EMPTY, 0, _blocks(disk), _read(disk, None)))
    (folder / STATE_NAME).write_bytes(state)

    # Act
    with pytest.raises(RescueError) as raised:
        load_folder(folder)

    # Assert
    assert f"{STATE_NAME} is not a rescue state" in str(raised.value)


def test_the_state_names_the_disk_and_each_side_read(tmp_path: Path) -> None:
    # Arrange
    disk = disk_with_a_file()
    folder = tmp_path / "rescue"

    # Act
    save_folder(folder, with_read(EMPTY, 0, _blocks(disk), _read(disk, None)))

    # Assert
    written = json.loads((folder / STATE_NAME).read_text(encoding="utf-8"))
    assert written["format"] == "fdstoolkit-rescue"
    assert written["sides"] == {"0": disk.sides[0].blocks[0].payload.hex()}
    assert set(written["identity"]) == {"licensee", "game", "version", "disk"}


def test_a_read_of_another_disk_is_refused() -> None:
    # Arrange
    disk = disk_with_a_file()
    other, _ = fds.decode(
        blank_image(sides=1, headered=False, formatted=True, game_name=OTHER_GAME)
    )
    state = with_read(EMPTY, 0, _blocks(disk), _read(disk, None))

    # Act
    problem = identity_problem(state, 0, _blocks(other))

    # Assert
    assert problem.startswith("this rescue is of ")
    assert problem.endswith("nothing was kept")


def test_a_read_of_the_other_face_is_refused() -> None:
    # Arrange
    two, _ = fds.decode(blank_image(sides=2, headered=False, formatted=True, game_name=OTHER_GAME))

    # Act
    problem = identity_problem(EMPTY, 0, _blocks(two, 1))

    # Assert
    assert problem == (
        "the disk in the drive shows side 1 face down, and this run reads side 0: "
        "turn the disk over"
    )


def test_a_side_whose_information_changed_is_refused() -> None:
    # Arrange
    disk = disk_with_a_file()
    state = with_read(EMPTY, 0, _blocks(disk), _read(disk, None))
    info = bytearray(disk.sides[0].blocks[0].payload)
    info[-1] ^= 1
    changed = (replace(_blocks(disk)[0], payload=bytes(info)), *_blocks(disk)[1:])

    # Act
    problem = identity_problem(state, 0, changed)

    # Assert
    assert problem == (
        "side 0 of the disk in the drive carries other disk information than the rescue "
        "recorded, so it was rewritten or is another copy; nothing was kept"
    )


def test_an_unreadable_disk_information_cannot_join_a_rescue_under_way() -> None:
    # Arrange
    disk = disk_with_a_file()
    state = with_read(EMPTY, 0, _blocks(disk), _read(disk, None))

    # Act
    problem = identity_problem(state, 0, _blocks(disk, bad_first=True))

    # Assert
    assert problem == (
        "the disk information did not read clean, so this read cannot be matched to the "
        "rescue; nothing was kept"
    )


def test_a_new_rescue_takes_a_first_read_whatever_its_disk_information() -> None:
    # Arrange
    disk = disk_with_a_file()

    # Act
    problem = identity_problem(EMPTY, 0, _blocks(disk, bad_first=True))

    # Assert
    assert problem == ""


def test_a_read_of_the_same_disk_is_accepted() -> None:
    # Arrange
    disk = disk_with_a_file()
    state = with_read(EMPTY, 0, _blocks(disk), _read(disk, None))

    # Act
    problem = identity_problem(state, 0, _blocks(disk))

    # Assert
    assert problem == ""


def test_an_identity_reads_as_the_game_it_names() -> None:
    # Arrange
    disk = disk_with_a_file()

    # Act
    state = with_read(EMPTY, 0, _blocks(disk), _read(disk, None))

    # Assert
    assert state.identity is not None
    assert state.identity.render().startswith(f"{state.identity.game} version ")
