from __future__ import annotations

import pytest

from fdstoolkit.build.fields import FieldError, as_int, mapping, number, objects, text


def test_a_value_that_is_not_an_object_is_refused_with_its_type() -> None:
    # Arrange
    value: object = ["sides"]

    # Act
    with pytest.raises(FieldError, match="the manifest is a JSON object, got list") as raised:
        mapping(value, where="the manifest")

    # Assert
    assert raised.type is FieldError


def test_a_list_field_holding_something_else_is_refused() -> None:
    # Arrange
    entry: dict[str, object] = {"files": "main.prg"}

    # Act
    with pytest.raises(FieldError, match="side 1: files is a list, got str") as raised:
        objects(entry, "files", where="side 1")

    # Assert
    assert raised.type is FieldError


def test_a_missing_list_field_reads_as_empty() -> None:
    # Arrange
    entry: dict[str, object] = {}

    # Act
    found = objects(entry, "files", where="side 1")

    # Assert
    assert found == ()


def test_a_required_field_that_is_missing_is_named() -> None:
    # Arrange
    entry: dict[str, object] = {"name": "MAIN"}

    # Act
    with pytest.raises(FieldError, match="side 1 file 1 has no path") as raised:
        text(entry, "path", where="side 1 file 1")

    # Assert
    assert raised.type is FieldError


def test_a_text_field_holding_a_number_is_refused() -> None:
    # Arrange
    entry: dict[str, object] = {"game_name": 7}

    # Act
    with pytest.raises(FieldError, match="recipe 1: game_name is text, got 7") as raised:
        text(entry, "game_name", where="recipe 1")

    # Assert
    assert raised.type is FieldError


def test_a_number_may_be_written_in_hex() -> None:
    # Arrange
    entry: dict[str, object] = {"address": "0x6000"}

    # Act
    found = number(entry, "address", where="side 1 file 1", limit=0xFFFF)

    # Assert
    assert found == 0x6000


def test_a_true_or_false_number_is_refused() -> None:
    # Arrange
    value: object = True

    # Act
    with pytest.raises(FieldError, match="side is a number, got True") as raised:
        as_int(value, key="side", where="")

    # Assert
    assert raised.type is FieldError


def test_text_that_is_not_a_number_is_refused_with_how_to_write_one() -> None:
    # Arrange
    entry: dict[str, object] = {"position": "third"}

    # Act
    with pytest.raises(FieldError, match="write it as 31 or 0x1F") as raised:
        number(entry, "position", where="recipe 1")

    # Assert
    assert raised.type is FieldError


def test_a_number_past_its_limit_is_refused_with_the_range() -> None:
    # Arrange
    entry: dict[str, object] = {"side": 2}

    # Act
    with pytest.raises(FieldError, match="side is 2, and it must be between 0 and 1") as raised:
        number(entry, "side", where="recipe 1", limit=1)

    # Assert
    assert raised.type is FieldError
