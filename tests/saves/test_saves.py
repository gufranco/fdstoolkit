from __future__ import annotations

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.disk import Disk
from fdstoolkit.edit.files import extract_files
from fdstoolkit.edit.saves import (
    SaveRecipe,
    find_save_candidates,
    name_looks_like_a_save,
    normalise_saves,
)


def disk_with(files: list[tuple[str, bytes]]) -> Disk:
    raw = bytearray(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    raw[56:58] = bytes([0x02, len(files)])
    position = 58
    for index, (name, payload) in enumerate(files):
        header = (
            bytes([0x03, index, index])
            + name.encode("ascii").ljust(8, b" ")
            + (0x6000).to_bytes(2, "little")
            + len(payload).to_bytes(2, "little")
            + bytes([0x00])
        )
        raw[position : position + 16] = header
        position += 16
        raw[position : position + 1 + len(payload)] = bytes([0x04]) + payload
        position += 1 + len(payload)
    disk, _ = decode(bytes(raw))
    return disk


def test_two_identical_dumps_have_no_candidates() -> None:
    disk = disk_with([("PROGRAM", bytes(8)), ("DATA", bytes(8))])

    assert find_save_candidates([disk, disk]) == ()


def test_a_file_that_differs_between_dumps_is_a_candidate() -> None:
    first = disk_with([("PROGRAM", bytes(8)), ("FC_SAVE", bytes(8))])
    second = disk_with([("PROGRAM", bytes(8)), ("FC_SAVE", bytes([0x7F]) * 8)])

    candidates = find_save_candidates([first, second])

    assert len(candidates) == 1
    assert candidates[0].name == "FC_SAVE"
    assert candidates[0].position == 1
    assert candidates[0].differing_bytes == 8


def test_every_file_differing_means_a_different_release_not_a_save() -> None:
    first = disk_with([("PROGRAM", bytes(8)), ("DATA", bytes(8))])
    second = disk_with([("PROGRAM", bytes([0x01]) * 8), ("DATA", bytes([0x02]) * 8)])

    assert find_save_candidates([first, second]) == ()


def test_candidates_need_at_least_two_dumps() -> None:
    with pytest.raises(ValueError, match="at least two"):
        find_save_candidates([disk_with([("PROGRAM", bytes(4))])])


def test_dumps_with_different_file_counts_are_refused() -> None:
    first = disk_with([("PROGRAM", bytes(4))])
    second = disk_with([("PROGRAM", bytes(4)), ("EXTRA", bytes(4))])

    with pytest.raises(ValueError, match="do not hold the same files"):
        find_save_candidates([first, second])


def test_a_name_that_reads_like_a_save_is_flagged() -> None:
    assert name_looks_like_a_save("FC_SAVE")
    assert name_looks_like_a_save("USR_DATA")
    assert name_looks_like_a_save("BACKUP")
    assert not name_looks_like_a_save("MAIN PRG")


def test_a_heuristic_name_alone_is_not_a_candidate() -> None:
    disk = disk_with([("FC_SAVE", bytes(8))])

    assert find_save_candidates([disk, disk]) == ()


def test_normalising_replaces_the_declared_file_with_the_fill() -> None:
    disk = disk_with([("PROGRAM", bytes(8)), ("FC_SAVE", bytes([0x7F]) * 8)])
    recipe = SaveRecipe(game_name="SMB", game_version=0, side=0, position=1, fill=0x00)

    updated, applied = normalise_saves(disk, [recipe])

    assert [entry.data for entry in extract_files(updated)][1] == bytes(8)
    assert [entry.position for entry in applied] == [1]


def test_normalising_leaves_a_disk_alone_when_no_recipe_matches() -> None:
    disk = disk_with([("PROGRAM", bytes(8))])
    recipe = SaveRecipe(game_name="ZEL", game_version=0, side=0, position=0, fill=0x00)

    updated, applied = normalise_saves(disk, [recipe])

    assert applied == ()
    assert extract_files(updated) == extract_files(disk)


def test_normalising_can_fill_with_any_byte() -> None:
    disk = disk_with([("FC_SAVE", bytes(4))])
    recipe = SaveRecipe(game_name="SMB", game_version=0, side=0, position=0, fill=0xFF)

    updated, _ = normalise_saves(disk, [recipe])

    assert extract_files(updated)[0].data == bytes([0xFF]) * 4


def test_a_recipe_that_names_a_missing_file_is_reported() -> None:
    disk = disk_with([("PROGRAM", bytes(4))])
    recipe = SaveRecipe(game_name="SMB", game_version=0, side=0, position=7, fill=0x00)

    with pytest.raises(ValueError, match="no file at position 7"):
        normalise_saves(disk, [recipe])


def test_normalising_makes_two_played_copies_agree() -> None:
    played = disk_with([("PROGRAM", bytes(8)), ("FC_SAVE", bytes([0x01]) * 8)])
    other = disk_with([("PROGRAM", bytes(8)), ("FC_SAVE", bytes([0x02]) * 8)])
    recipe = SaveRecipe(game_name="SMB", game_version=0, side=0, position=1, fill=0x00)

    first, _ = normalise_saves(played, [recipe])
    second, _ = normalise_saves(other, [recipe])

    assert extract_files(first) == extract_files(second)


def test_a_recipe_for_a_side_that_does_not_exist_is_ignored() -> None:
    disk = disk_with([("PROGRAM", bytes(4))])
    recipe = SaveRecipe(game_name="SMB", game_version=0, side=4, position=0, fill=0x00)

    _, applied = normalise_saves(disk, [recipe])

    assert applied == ()


def test_a_recipe_for_an_unformatted_side_is_ignored() -> None:
    unformatted, _ = decode(blank_image(sides=1, headered=False, formatted=False))
    recipe = SaveRecipe(game_name="SMB", game_version=0, side=0, position=0, fill=0x00)

    _, applied = normalise_saves(unformatted, [recipe])

    assert applied == ()


def test_a_recipe_naming_a_header_without_data_is_reported() -> None:
    disk = disk_with([("FC_SAVE", bytes(4))])
    side = disk.sides[0]
    orphaned = side.__class__(blocks=side.blocks[:-1], tail=b"", capacity=side.capacity)
    recipe = SaveRecipe(game_name="SMB", game_version=0, side=0, position=0, fill=0x00)

    with pytest.raises(ValueError, match="no file at position 0"):
        normalise_saves(Disk(sides=(orphaned,)), [recipe])
