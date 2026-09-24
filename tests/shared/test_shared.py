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
    assert bytes_of(ENCODED) == IMAGE


def test_a_payload_that_is_not_base64_is_refused() -> None:
    with pytest.raises(HTTPException) as caught:
        bytes_of("not base64 at all!!")

    assert caught.value.status_code == BAD_REQUEST


def test_an_empty_payload_is_refused() -> None:
    with pytest.raises(HTTPException) as caught:
        bytes_of("")

    assert caught.value.status_code == BAD_REQUEST


def test_an_image_decodes_to_a_disk() -> None:
    disk, data, findings = decode_payload(ENCODED)

    assert len(disk.sides) == 1
    assert data == IMAGE
    assert findings == ()


def test_an_image_from_another_system_is_refused() -> None:
    hxc = base64.b64encode(b"HXCQDDRV" + bytes(56)).decode("ascii")

    with pytest.raises(HTTPException) as caught:
        decode_payload(hxc)

    assert caught.value.status_code == BAD_REQUEST


def test_a_disk_encodes_back_to_the_bytes_it_came_from() -> None:
    disk, _, _ = decode_payload(ENCODED)

    assert encoded(disk) == IMAGE


def test_a_headered_encoding_is_longer() -> None:
    disk, _, _ = decode_payload(ENCODED)

    assert len(encoded(disk, headered=True)) > len(IMAGE)


def test_a_named_file_carries_its_size_and_payload() -> None:
    result = named_file("disk.fds", IMAGE)

    assert result.name == "disk.fds"
    assert result.size == len(IMAGE)
    assert base64.b64decode(result.data) == IMAGE


def test_a_refusal_carries_the_status_it_was_given() -> None:
    with pytest.raises(HTTPException) as caught:
        refuse("no", status=UNPROCESSABLE)

    assert caught.value.status_code == UNPROCESSABLE


def test_dataclasses_render_as_rows() -> None:
    assert rows_of([Note(name="a", count=1)]) == [{"name": "a", "count": 1}]


def test_dictionaries_render_as_rows() -> None:
    assert rows_of([{"name": "a"}]) == [{"name": "a"}]


def test_anything_else_renders_as_a_value() -> None:
    assert rows_of(["plain"]) == [{"value": "plain"}]


def test_an_empty_rows_result_carries_an_empty_list() -> None:
    assert RowsResult().rows == []
    assert FilesResult().files == []
