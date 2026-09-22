from __future__ import annotations

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.disk import Disk
from fdstoolkit.core.diskinfo import DiskInfo
from fdstoolkit.edit.diskinfo import EDITABLE_FIELDS, apply_edits, parse_edit


def sample() -> Disk:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    return disk


def info_of(disk: Disk, side: int = 0) -> DiskInfo:
    block = disk.sides[side].blocks[0]
    return DiskInfo.parse(block.payload)


def test_a_text_field_is_written_padded() -> None:
    updated, changes = apply_edits(sample(), side=0, edits={"game_name": "ZEL"})

    assert info_of(updated).game_name == "ZEL"
    assert changes[0].field == "game_name"


def test_a_numeric_field_is_written() -> None:
    updated, _ = apply_edits(sample(), side=0, edits={"game_version": 3})

    assert info_of(updated).game_version == 3


def test_a_date_is_written_in_bcd() -> None:
    updated, _ = apply_edits(sample(), side=0, edits={"manufacturing_date": "1987-05-09"})

    assert info_of(updated).manufacturing_date == (1987, 5, 9)


def test_a_change_reports_the_old_and_the_new_value() -> None:
    _, changes = apply_edits(sample(), side=0, edits={"game_name": "ZEL"})

    assert changes[0].before == "SMB"
    assert changes[0].after == "ZEL"


def test_editing_nothing_changes_nothing() -> None:
    disk = sample()

    updated, changes = apply_edits(disk, side=0, edits={})

    assert updated == disk
    assert changes == ()


def test_editing_keeps_the_rest_of_the_block() -> None:
    updated, _ = apply_edits(sample(), side=0, edits={"game_name": "ZEL"})

    assert info_of(updated).is_verified
    assert info_of(updated).country == 0x49


def test_an_unknown_field_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown field"):
        apply_edits(sample(), side=0, edits={"colour": "blue"})


def test_a_field_that_is_not_editable_is_refused() -> None:
    with pytest.raises(ValueError, match="not editable"):
        apply_edits(sample(), side=0, edits={"verification": "x"})


def test_a_side_that_does_not_exist_is_refused() -> None:
    with pytest.raises(ValueError, match="no side 3"):
        apply_edits(sample(), side=3, edits={"game_name": "ZEL"})


def test_an_unformatted_side_cannot_be_edited() -> None:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=False))

    with pytest.raises(ValueError, match="no disk information block"):
        apply_edits(disk, side=0, edits={"game_name": "ZEL"})


def test_a_text_value_longer_than_its_field_is_refused() -> None:
    with pytest.raises(ValueError, match="3 byte"):
        apply_edits(sample(), side=0, edits={"game_name": "TOOLONG"})


def test_a_numeric_value_outside_a_byte_is_refused() -> None:
    with pytest.raises(ValueError, match="between 0 and 255"):
        apply_edits(sample(), side=0, edits={"game_version": 300})


def test_an_edit_string_is_parsed_into_a_pair() -> None:
    assert parse_edit("game_name=ZEL") == ("game_name", "ZEL")


def test_an_edit_string_without_an_equals_sign_is_refused() -> None:
    with pytest.raises(ValueError, match="field=value"):
        parse_edit("game_name")


def test_every_editable_field_is_named() -> None:
    assert "game_name" in EDITABLE_FIELDS
    assert "verification" not in EDITABLE_FIELDS


def test_a_date_that_is_not_a_date_is_refused() -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        apply_edits(sample(), side=0, edits={"manufacturing_date": "yesterday"})
