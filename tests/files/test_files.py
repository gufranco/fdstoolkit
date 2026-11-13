from __future__ import annotations

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode, encode
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.core.files import extract_files
from fdstoolkit.edit.files import (
    FileSpec,
    declared_file_count,
    insert_file,
    remove_file,
    set_declared_file_count,
)


def disk_with(files: int = 1, *, declared: int | None = None) -> Disk:
    raw = bytearray(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    raw[56:58] = bytes([0x02, files if declared is None else declared])
    position = 58
    for index in range(files):
        header = (
            bytes([0x03, index, index])
            + f"FILE{index}   ".encode("ascii")[:8]
            + (0x6000 + index).to_bytes(2, "little")
            + (4).to_bytes(2, "little")
            + bytes([0x00])
        )
        raw[position : position + 16] = header
        position += 16
        raw[position : position + 5] = bytes([0x04]) + bytes([(0xA0 + index) & 0xFF]) * 4
        position += 5
    disk, _ = decode(bytes(raw))
    return disk


def test_extracting_returns_one_entry_per_file() -> None:
    # Arrange
    disk = disk_with(files=3)

    # Act
    files = extract_files(disk)

    # Assert
    assert len(files) == 3
    assert [entry.name for entry in files] == ["FILE0", "FILE1", "FILE2"]


def test_an_extracted_file_carries_its_data_without_the_block_code() -> None:
    # Arrange
    expected = bytes([0xA0]) * 4

    # Act
    entry = extract_files(disk_with())[0]

    # Assert
    assert entry.data == expected
    assert entry.size == 4
    assert entry.kind is FileKind.PROGRAM
    assert entry.address == 0x6000


def test_an_extracted_file_knows_its_side_and_position() -> None:
    # Arrange
    expected = 0

    # Act
    entry = extract_files(disk_with(files=2))[1]

    # Assert
    assert entry.side == expected
    assert entry.position == 1


def test_a_file_past_the_declared_count_is_marked_hidden() -> None:
    # Arrange
    disk = disk_with(files=3, declared=1)

    # Act
    files = extract_files(disk)

    # Assert
    assert [entry.hidden for entry in files] == [False, True, True]


def test_inserting_adds_a_file_at_the_end() -> None:
    # Arrange
    spec = FileSpec(name="NEW", address=0x7000, kind=FileKind.CHARACTER, data=bytes([0x11]) * 8)
    updated = insert_file(disk_with(files=1), side=0, spec=spec)

    # Act
    files = extract_files(updated)

    # Assert
    assert [entry.name for entry in files] == ["FILE0", "NEW"]
    assert files[1].data == bytes([0x11]) * 8
    assert files[1].kind is FileKind.CHARACTER


def test_inserting_raises_the_declared_count() -> None:
    # Arrange
    disk = disk_with(files=1)
    side = 0
    spec = FileSpec(name="NEW", address=0x7000, kind=FileKind.PROGRAM, data=b"\x01")

    # Act
    updated = insert_file(
        disk,
        side=side,
        spec=spec,
    )

    # Assert
    assert declared_file_count(updated, side=0) == 2


def test_inserting_keeps_the_image_parseable() -> None:
    # Arrange
    updated = insert_file(
        disk_with(files=1),
        side=0,
        spec=FileSpec(name="NEW", address=0x7000, kind=FileKind.PROGRAM, data=b"\x01" * 16),
    )
    data, _ = encode(updated, headered=False)

    # Act
    reparsed, findings = decode(data)

    # Assert
    assert [finding.code for finding in findings] == []
    assert reparsed.sides[0].file_count == 2


def test_inserting_a_file_that_does_not_fit_is_refused() -> None:
    # Arrange
    spec = FileSpec(name="BIG", address=0x6000, kind=FileKind.PROGRAM, data=bytes(65500))

    # Act
    with pytest.raises(ValueError, match="does not fit") as raised:
        insert_file(disk_with(files=1), side=0, spec=spec)

    # Assert
    assert raised.type is ValueError


def test_inserting_past_255_files_is_refused_whatever_the_declared_count() -> None:
    # Arrange
    spec = FileSpec(name="MORE", address=0x6000, kind=FileKind.PROGRAM, data=bytes(4))

    # Act
    with pytest.raises(ValueError, match="at most 255 files") as raised:
        insert_file(disk_with(files=255, declared=0), side=0, spec=spec)

    # Assert
    assert raised.type is ValueError


def test_a_name_longer_than_eight_characters_is_refused() -> None:
    # Arrange
    spec = FileSpec(name="TOOLONGNAME", address=0x6000, kind=FileKind.PROGRAM, data=b"\x01")

    # Act
    with pytest.raises(ValueError, match="eight characters") as raised:
        insert_file(disk_with(), side=0, spec=spec)

    # Assert
    assert raised.type is ValueError


def test_inserting_into_a_side_that_does_not_exist_is_refused() -> None:
    # Arrange
    spec = FileSpec(name="NEW", address=0x6000, kind=FileKind.PROGRAM, data=b"\x01")

    # Act
    with pytest.raises(ValueError, match="no side 4") as raised:
        insert_file(disk_with(), side=4, spec=spec)

    # Assert
    assert raised.type is ValueError


def test_removing_drops_the_file_and_its_header() -> None:
    # Arrange
    updated = remove_file(disk_with(files=3), side=0, position=1)

    # Act
    files = extract_files(updated)

    # Assert
    assert [entry.name for entry in files] == ["FILE0", "FILE2"]
    assert declared_file_count(updated, side=0) == 2


def test_removing_a_position_that_does_not_exist_is_refused() -> None:
    # Arrange
    disk = disk_with(files=1)
    side = 0
    position = 9

    # Act
    with pytest.raises(ValueError, match="no file at position 9") as raised:
        remove_file(disk, side=side, position=position)

    # Assert
    assert raised.type is ValueError


def test_the_declared_count_can_be_set_without_touching_the_files() -> None:
    # Arrange
    disk = disk_with(files=3)
    side = 0
    count = 1

    # Act
    updated = set_declared_file_count(disk, side=side, count=count)

    # Assert
    assert declared_file_count(updated, side=0) == 1
    assert len(extract_files(updated)) == 3
    assert [entry.hidden for entry in extract_files(updated)] == [False, True, True]


def test_a_declared_count_beyond_the_files_present_is_refused() -> None:
    # Arrange
    disk = disk_with(files=1)
    side = 0
    count = 5

    # Act
    with pytest.raises(ValueError, match="only 1 file") as raised:
        set_declared_file_count(disk, side=side, count=count)

    # Assert
    assert raised.type is ValueError


def test_an_unformatted_side_has_no_declared_count() -> None:
    # Arrange
    data = blank_image(sides=1, headered=False, formatted=False)

    # Act
    disk, _ = decode(data)

    # Assert
    assert declared_file_count(disk, side=0) is None


def test_a_side_that_already_declares_the_maximum_refuses_another_file() -> None:
    # Arrange
    crowded = set_declared_file_count(disk_with(files=1), side=0, count=1)
    full = Side(
        blocks=tuple(
            Block(kind=block.kind, payload=bytes([0x02, 0xFF]))
            if block.kind is BlockKind.FILE_AMOUNT
            else block
            for block in crowded.sides[0].blocks
        ),
        tail=b"",
        capacity=crowded.sides[0].capacity,
    )
    spec = FileSpec(name="NEW", address=0x6000, kind=FileKind.PROGRAM, data=b"\x01")

    # Act
    with pytest.raises(ValueError, match="at most 255") as raised:
        insert_file(Disk(sides=(full,)), side=0, spec=spec)

    # Assert
    assert raised.type is ValueError


def test_removing_a_header_without_its_data_block_drops_only_the_header() -> None:
    # Arrange
    disk = disk_with(files=1)
    side = disk.sides[0]
    orphaned = side.__class__(blocks=side.blocks[:-1], tail=b"", capacity=side.capacity)

    # Act
    updated = remove_file(Disk(sides=(orphaned,)), side=0, position=0)

    # Assert
    assert extract_files(updated) == ()
