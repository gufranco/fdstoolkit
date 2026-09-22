from __future__ import annotations

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import SIDE_SIZE, decode, encode
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.edit.clean import clean_trailing_data


def with_tail(tail: bytes) -> Disk:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    side = disk.sides[0]
    return Disk(sides=(Side(blocks=side.blocks, tail=tail, capacity=side.capacity),))


def test_a_clean_side_is_left_alone() -> None:
    disk = with_tail(b"")

    cleaned, removed = clean_trailing_data(disk)

    assert removed == ()
    assert cleaned.sides[0].tail == b""


def test_trailing_data_is_removed_and_reported() -> None:
    disk = with_tail(bytes([0xDE, 0xAD, 0xBE, 0xEF]))

    cleaned, removed = clean_trailing_data(disk)

    assert cleaned.sides[0].tail == b""
    assert removed[0].side == 0
    assert removed[0].bytes_removed == 4


def test_the_removed_bytes_are_kept_in_the_report() -> None:
    disk = with_tail(bytes([0x01, 0x02]))

    _, removed = clean_trailing_data(disk)

    assert removed[0].data == bytes([0x01, 0x02])


def test_a_cleaned_image_keeps_its_nominal_size() -> None:
    disk = with_tail(bytes([0xFF]) * 100)

    cleaned, _ = clean_trailing_data(disk)
    data, _ = encode(cleaned, headered=False)

    assert len(data) == SIDE_SIZE


def test_every_side_is_cleaned() -> None:
    one = with_tail(bytes([0x01])).sides[0]
    two = with_tail(bytes([0x02])).sides[0]

    cleaned, removed = clean_trailing_data(Disk(sides=(one, two)))

    assert [entry.side for entry in removed] == [0, 1]
    assert all(side.tail == b"" for side in cleaned.sides)


def test_cleaning_is_idempotent() -> None:
    disk = with_tail(bytes([0x09]))

    once, _ = clean_trailing_data(disk)
    twice, removed = clean_trailing_data(once)

    assert twice == once
    assert removed == ()
