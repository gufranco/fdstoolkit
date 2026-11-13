from __future__ import annotations

import base64
from dataclasses import dataclass

import pytest
from fastapi import HTTPException

from fdstoolkit.build.blank import blank_image
from fdstoolkit.ui.schemas import FilesResult, RowsResult
from fdstoolkit.ui.shared import (
    BAD_REQUEST,
    UNPROCESSABLE,
    bytes_of,
    decode_payload,
    encoded,
    encoded_file,
    named_file,
    refuse,
    rows_of,
)

IMAGE = blank_image(sides=1, headered=False, formatted=True, game_name="SMB")
ENCODED = base64.b64encode(IMAGE).decode("ascii")


@dataclass(frozen=True, slots=True)
class Note:
    name: str
    count: int


def test_a_base64_payload_decodes_to_its_bytes() -> None:
    # Arrange
    payload = ENCODED

    # Act
    decoded = bytes_of(payload)

    # Assert
    assert decoded == IMAGE


def test_a_payload_that_is_not_base64_is_refused() -> None:
    # Arrange
    payload = "not base64 at all!!"

    # Act
    with pytest.raises(HTTPException) as caught:
        bytes_of(payload)

    # Assert
    assert caught.type is HTTPException
    assert caught.value.status_code == BAD_REQUEST


def test_an_empty_payload_is_refused() -> None:
    # Arrange
    payload = ""

    # Act
    with pytest.raises(HTTPException) as caught:
        bytes_of(payload)

    # Assert
    assert caught.type is HTTPException
    assert caught.value.status_code == BAD_REQUEST


def test_an_image_decodes_to_a_disk() -> None:
    # Arrange
    expected = 1

    # Act
    disk, data, findings = decode_payload(ENCODED)

    # Assert
    assert len(disk.sides) == expected
    assert data == IMAGE
    assert findings == ()


def test_an_image_from_another_system_is_refused() -> None:
    # Arrange
    hxc = base64.b64encode(b"HXCQDDRV" + bytes(56)).decode("ascii")

    # Act
    with pytest.raises(HTTPException) as caught:
        decode_payload(hxc)

    # Assert
    assert caught.type is HTTPException
    assert caught.value.status_code == BAD_REQUEST


def test_a_disk_encodes_back_to_the_bytes_it_came_from() -> None:
    # Arrange
    expected = (IMAGE, ())

    # Act
    disk, _, _ = decode_payload(ENCODED)

    # Assert
    assert encoded(disk) == expected


def test_a_headered_encoding_is_longer() -> None:
    # Arrange
    expected = len(IMAGE)

    # Act
    disk, _, _ = decode_payload(ENCODED)

    # Assert
    assert len(encoded(disk, headered=True)[0]) > expected


def test_a_named_file_carries_its_size_and_payload() -> None:
    # Arrange
    name = "disk.fds"

    # Act
    result = named_file(name, IMAGE)

    # Assert
    assert result.name == "disk.fds"
    assert result.size == len(IMAGE)
    assert base64.b64decode(result.data) == IMAGE


def test_a_refusal_carries_the_status_it_was_given() -> None:
    # Arrange
    message = "no"

    # Act
    with pytest.raises(HTTPException) as caught:
        refuse(message, status=UNPROCESSABLE)

    # Assert
    assert caught.type is HTTPException
    assert caught.value.status_code == UNPROCESSABLE


def test_dataclasses_render_as_rows() -> None:
    # Arrange
    items = [Note(name="a", count=1)]

    # Act
    result = rows_of(items)

    # Assert
    assert result == [{"name": "a", "count": 1}]


def test_dictionaries_render_as_rows() -> None:
    # Arrange
    items = [{"name": "a"}]

    # Act
    result = rows_of(items)

    # Assert
    assert result == [{"name": "a"}]


def test_anything_else_renders_as_a_value() -> None:
    # Arrange
    items = ["plain"]

    # Act
    result = rows_of(items)

    # Assert
    assert result == [{"value": "plain"}]


def test_an_empty_rows_result_carries_an_empty_list() -> None:
    # Arrange
    expected = []

    # Act
    result = RowsResult().rows

    # Assert
    assert result == expected
    assert FilesResult().files == []


def test_a_qd_file_keeps_the_checksums_and_says_nothing_extra() -> None:
    # Arrange
    disk, _, _ = decode_payload(base64.b64encode(IMAGE).decode("ascii"))

    # Act
    result = encoded_file("dump.qd", disk)

    # Assert
    assert result.name == "dump.qd"
    assert result.notes == []
    assert result.size % 65536 == 0
