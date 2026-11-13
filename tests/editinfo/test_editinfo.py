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
    # Arrange
    disk = sample()
    side = 0
    edits = {"game_name": "ZEL"}

    # Act
    updated, changes = apply_edits(disk, side=side, edits=edits)

    # Assert
    assert info_of(updated).game_name == "ZEL"
    assert changes[0].field == "game_name"


def test_a_numeric_field_is_written() -> None:
    # Arrange
    disk = sample()
    side = 0
    edits = {"game_version": 3}

    # Act
    updated, _ = apply_edits(disk, side=side, edits=edits)

    # Assert
    assert info_of(updated).game_version == 3


def test_a_date_is_written_in_bcd() -> None:
    # Arrange
    disk = sample()
    side = 0
    edits = {"manufacturing_date": "1987-05-09"}

    # Act
    updated, _ = apply_edits(disk, side=side, edits=edits)

    # Assert
    assert info_of(updated).manufacturing_date == (1987, 5, 9)


def test_a_change_reports_the_old_and_the_new_value() -> None:
    # Arrange
    disk = sample()
    side = 0
    edits = {"game_name": "ZEL"}

    # Act
    _, changes = apply_edits(disk, side=side, edits=edits)

    # Assert
    assert changes[0].before == "SMB"
    assert changes[0].after == "ZEL"


def test_editing_nothing_changes_nothing() -> None:
    # Arrange
    disk = sample()

    # Act
    updated, changes = apply_edits(disk, side=0, edits={})

    # Assert
    assert updated == disk
    assert changes == ()


def test_editing_keeps_the_rest_of_the_block() -> None:
    # Arrange
    disk = sample()
    side = 0
    edits = {"game_name": "ZEL"}

    # Act
    updated, _ = apply_edits(disk, side=side, edits=edits)

    # Assert
    assert info_of(updated).is_verified
    assert info_of(updated).country == 0x49


def test_an_unknown_field_is_refused() -> None:
    # Arrange
    disk = sample()
    side = 0
    edits = {"colour": "blue"}

    # Act
    with pytest.raises(ValueError, match="unknown field") as raised:
        apply_edits(disk, side=side, edits=edits)

    # Assert
    assert raised.type is ValueError


def test_a_field_that_is_not_editable_is_refused() -> None:
    # Arrange
    disk = sample()
    side = 0
    edits = {"verification": "x"}

    # Act
    with pytest.raises(ValueError, match="not editable") as raised:
        apply_edits(disk, side=side, edits=edits)

    # Assert
    assert raised.type is ValueError


def test_a_side_that_does_not_exist_is_refused() -> None:
    # Arrange
    disk = sample()
    side = 3
    edits = {"game_name": "ZEL"}

    # Act
    with pytest.raises(ValueError, match="no side 3") as raised:
        apply_edits(disk, side=side, edits=edits)

    # Assert
    assert raised.type is ValueError


def test_an_unformatted_side_cannot_be_edited() -> None:
    # Arrange
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=False))

    # Act
    with pytest.raises(ValueError, match="no disk information block") as raised:
        apply_edits(disk, side=0, edits={"game_name": "ZEL"})

    # Assert
    assert raised.type is ValueError


def test_a_text_value_longer_than_its_field_is_refused() -> None:
    # Arrange
    disk = sample()
    side = 0
    edits = {"game_name": "TOOLONG"}

    # Act
    with pytest.raises(ValueError, match="3 byte") as raised:
        apply_edits(disk, side=side, edits=edits)

    # Assert
    assert raised.type is ValueError


def test_a_numeric_value_outside_a_byte_is_refused() -> None:
    # Arrange
    disk = sample()
    side = 0
    edits = {"game_version": 300}

    # Act
    with pytest.raises(ValueError, match="between 0 and 255") as raised:
        apply_edits(disk, side=side, edits=edits)

    # Assert
    assert raised.type is ValueError


def test_an_edit_string_is_parsed_into_a_pair() -> None:
    # Arrange
    text = "game_name=ZEL"

    # Act
    result = parse_edit(text)

    # Assert
    assert result == ("game_name", "ZEL")


def test_an_edit_string_without_an_equals_sign_is_refused() -> None:
    # Arrange
    text = "game_name"

    # Act
    with pytest.raises(ValueError, match="field=value") as raised:
        parse_edit(text)

    # Assert
    assert raised.type is ValueError


def test_every_editable_field_is_named() -> None:
    # Arrange
    fields = EDITABLE_FIELDS

    # Act
    names = set(fields)

    # Assert
    assert "game_name" in names
    assert "verification" not in names


def test_a_date_that_is_not_a_date_is_refused() -> None:
    # Arrange
    disk = sample()
    side = 0
    edits = {"manufacturing_date": "yesterday"}

    # Act
    with pytest.raises(ValueError, match="YYYY-MM-DD") as raised:
        apply_edits(disk, side=side, edits=edits)

    # Assert
    assert raised.type is ValueError
