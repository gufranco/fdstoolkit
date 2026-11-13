from __future__ import annotations

from dataclasses import replace

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.qd import decode as decode_qd
from fdstoolkit.codecs.qd import encode as encode_qd
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.edit.files import FileSpec, insert_file
from fdstoolkit.edit.rebuild import RebuildOptions, rebuild


def sample(*, files: int = 1) -> Disk:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    for index in range(files):
        disk = insert_file(
            disk,
            side=0,
            spec=FileSpec(
                name=f"F{index}",
                address=0x6000,
                kind=FileKind.PROGRAM,
                data=bytes([index + 1]) * 4,
            ),
        )
    return disk


def with_crcs(disk: Disk) -> Disk:
    data, _ = encode_qd(disk)
    rebuilt, _ = decode_qd(data)
    return rebuilt


def patch_side(disk: Disk, blocks: tuple[Block, ...], *, tail: bytes | None = None) -> Disk:
    side = disk.sides[0]
    return Disk(
        sides=(replace(side, blocks=blocks, tail=side.tail if tail is None else tail),),
        header_side_count=disk.header_side_count,
    )


def set_file_amount(disk: Disk, count: int) -> Disk:
    blocks = tuple(
        Block(kind=block.kind, payload=bytes([BlockKind.FILE_AMOUNT, count]))
        if block.kind is BlockKind.FILE_AMOUNT
        else block
        for block in disk.sides[0].blocks
    )
    return patch_side(disk, blocks)


def actions(disk: Disk, **options: bool) -> tuple[str, ...]:
    _, report = rebuild(disk, options=RebuildOptions(**options))
    return tuple(action.kind for action in report.actions)


def test_a_clean_disk_needs_no_action() -> None:
    # Arrange
    disk = sample()

    # Act
    result, report = rebuild(disk)

    # Assert
    assert report.actions == ()
    assert result == sample()


def test_a_null_crc_is_recomputed() -> None:
    # Arrange
    source = with_crcs(sample())
    blocks = (source.sides[0].blocks[0].with_null_crc(), *source.sides[0].blocks[1:])

    # Act
    result, report = rebuild(patch_side(source, blocks))

    # Assert
    assert result.sides[0].blocks[0].stored_crc == source.sides[0].blocks[0].computed_crc
    assert [action.kind for action in report.actions] == ["crc"]


def test_a_mismatched_crc_is_recomputed() -> None:
    # Arrange
    source = with_crcs(sample())
    first = source.sides[0].blocks[0]
    blocks = (
        Block(kind=first.kind, payload=first.payload, stored_crc=0x1234),
        *source.sides[0].blocks[1:],
    )

    # Act
    result, _ = rebuild(patch_side(source, blocks))

    # Assert
    assert result.sides[0].blocks[0].stored_crc == first.computed_crc


def test_an_image_without_crcs_keeps_none() -> None:
    # Arrange
    disk = sample()

    # Act
    result, report = rebuild(disk)

    # Assert
    assert all(block.stored_crc is None for block in result.sides[0].blocks)
    assert report.actions == ()


def test_a_wrong_declared_file_size_is_corrected() -> None:
    # Arrange
    disk = sample()
    header = next(block for block in disk.sides[0].blocks if block.kind is BlockKind.FILE_HEADER)
    payload = bytearray(header.payload)
    payload[0x0D:0x0F] = (99).to_bytes(2, "little")
    blocks = tuple(
        Block(kind=block.kind, payload=bytes(payload)) if block is header else block
        for block in disk.sides[0].blocks
    )
    result, report = rebuild(patch_side(disk, blocks))

    # Act
    fixed = next(block for block in result.sides[0].blocks if block.kind is BlockKind.FILE_HEADER)

    # Assert
    assert int.from_bytes(fixed.payload[0x0D:0x0F], "little") == 4
    assert [action.kind for action in report.actions] == ["file_size"]


def test_trailing_data_is_dropped() -> None:
    # Arrange
    disk = patch_side(sample(), sample().sides[0].blocks, tail=b"junk")

    # Act
    result, report = rebuild(disk)

    # Assert
    assert result.sides[0].tail == b""
    assert [action.kind for action in report.actions] == ["tail"]


def test_trailing_data_can_be_kept() -> None:
    # Arrange
    disk = patch_side(sample(), sample().sides[0].blocks, tail=b"junk")

    # Act
    result, report = rebuild(disk, options=RebuildOptions(keep_tail=True))

    # Assert
    assert result.sides[0].tail == b"junk"
    assert report.actions == ()


def test_hidden_files_survive_by_default() -> None:
    # Arrange
    disk = set_file_amount(sample(files=2), 1)

    # Act
    result, report = rebuild(disk)

    # Assert
    assert result.sides[0].file_count == 2
    assert result.sides[0].hidden_file_count == 1
    assert report.actions == ()


def test_hidden_files_can_be_revealed() -> None:
    # Arrange
    disk = set_file_amount(sample(files=2), 1)

    # Act
    result, report = rebuild(disk, options=RebuildOptions(reveal_hidden=True))

    # Assert
    assert result.sides[0].declared_file_count == 2
    assert result.sides[0].hidden_file_count == 0
    assert [action.kind for action in report.actions] == ["reveal"]


def test_hidden_files_can_be_dropped() -> None:
    # Arrange
    disk = set_file_amount(sample(files=2), 1)

    # Act
    result, report = rebuild(disk, options=RebuildOptions(drop_hidden=True))

    # Assert
    assert result.sides[0].file_count == 1
    assert [action.kind for action in report.actions] == ["drop_hidden"]


def test_dropping_nothing_reports_nothing() -> None:
    # Arrange
    disk = sample(files=2)
    options = RebuildOptions(drop_hidden=True)

    # Act
    result, report = rebuild(disk, options=options)

    # Assert
    assert result.sides[0].file_count == 2
    assert report.actions == ()


def test_revealing_nothing_reports_nothing() -> None:
    # Arrange
    reveal_hidden = True

    # Act
    result = actions(sample(files=2), reveal_hidden=reveal_hidden)

    # Assert
    assert result == ()


def test_revealing_and_dropping_together_is_refused() -> None:
    # Arrange
    disk = sample()
    options = RebuildOptions(reveal_hidden=True, drop_hidden=True)

    # Act
    with pytest.raises(ValueError, match="either reveal or drop") as raised:
        rebuild(disk, options=options)

    # Assert
    assert raised.type is ValueError


def test_files_can_be_renumbered() -> None:
    # Arrange
    disk = sample(files=2)
    headers = [block for block in disk.sides[0].blocks if block.kind is BlockKind.FILE_HEADER]
    payload = bytearray(headers[1].payload)
    payload[1] = 9
    blocks = tuple(
        Block(kind=block.kind, payload=bytes(payload)) if block is headers[1] else block
        for block in disk.sides[0].blocks
    )
    renumbered = patch_side(disk, blocks)

    # Act
    result, report = rebuild(renumbered, options=RebuildOptions(renumber=True))

    # Assert
    assert [header.number for header in result.sides[0].file_headers] == [0, 1]
    assert [action.kind for action in report.actions] == ["renumber"]


def test_renumbering_an_already_ordered_side_reports_nothing() -> None:
    # Arrange
    renumber = True

    # Act
    result = actions(sample(files=2), renumber=renumber)

    # Assert
    assert result == ()


def test_an_unformatted_side_is_left_alone() -> None:
    # Arrange
    blank, _ = decode(blank_image(sides=1, headered=False, formatted=False))

    # Act
    result, report = rebuild(blank)

    # Assert
    assert result == blank
    assert report.actions == ()


def test_a_header_without_data_is_left_alone() -> None:
    # Arrange
    disk = sample()
    blocks = tuple(block for block in disk.sides[0].blocks if block.kind is not BlockKind.FILE_DATA)

    # Act
    result, report = rebuild(patch_side(disk, blocks))

    # Assert
    assert report.actions == ()
    assert len(result.sides[0].blocks) == len(blocks)


def test_every_side_is_rebuilt() -> None:
    # Arrange
    one = sample().sides[0]
    other = Side(blocks=one.blocks, tail=b"junk", capacity=one.capacity)
    disk = Disk(sides=(one, other))

    # Act
    _, report = rebuild(disk)

    # Assert
    assert [action.side for action in report.actions] == [1]


def test_a_hidden_header_without_data_is_dropped() -> None:
    # Arrange
    disk = set_file_amount(sample(files=1), 0)
    blocks = tuple(block for block in disk.sides[0].blocks if block.kind is not BlockKind.FILE_DATA)

    # Act
    result, report = rebuild(patch_side(disk, blocks), options=RebuildOptions(drop_hidden=True))

    # Assert
    assert result.sides[0].file_headers == ()
    assert [action.kind for action in report.actions] == ["drop_hidden"]
