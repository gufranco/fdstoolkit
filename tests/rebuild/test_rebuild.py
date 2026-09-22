from __future__ import annotations

from dataclasses import replace

import pytest

from fdstk.build.blank import blank_image
from fdstk.codecs.fds import decode
from fdstk.codecs.qd import decode as decode_qd
from fdstk.codecs.qd import encode as encode_qd
from fdstk.core.blocks import Block, BlockKind, FileKind
from fdstk.core.disk import Disk, Side
from fdstk.edit.files import FileSpec, insert_file
from fdstk.edit.rebuild import RebuildOptions, rebuild


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
    result, report = rebuild(sample())

    assert report.actions == ()
    assert result == sample()


def test_a_null_crc_is_recomputed() -> None:
    source = with_crcs(sample())
    blocks = (source.sides[0].blocks[0].with_null_crc(), *source.sides[0].blocks[1:])

    result, report = rebuild(patch_side(source, blocks))

    assert result.sides[0].blocks[0].stored_crc == source.sides[0].blocks[0].computed_crc
    assert [action.kind for action in report.actions] == ["crc"]


def test_a_mismatched_crc_is_recomputed() -> None:
    source = with_crcs(sample())
    first = source.sides[0].blocks[0]
    blocks = (
        Block(kind=first.kind, payload=first.payload, stored_crc=0x1234),
        *source.sides[0].blocks[1:],
    )

    result, _ = rebuild(patch_side(source, blocks))

    assert result.sides[0].blocks[0].stored_crc == first.computed_crc


def test_an_image_without_crcs_keeps_none() -> None:
    result, report = rebuild(sample())

    assert all(block.stored_crc is None for block in result.sides[0].blocks)
    assert report.actions == ()


def test_a_wrong_declared_file_size_is_corrected() -> None:
    disk = sample()
    header = next(block for block in disk.sides[0].blocks if block.kind is BlockKind.FILE_HEADER)
    payload = bytearray(header.payload)
    payload[0x0D:0x0F] = (99).to_bytes(2, "little")
    blocks = tuple(
        Block(kind=block.kind, payload=bytes(payload)) if block is header else block
        for block in disk.sides[0].blocks
    )

    result, report = rebuild(patch_side(disk, blocks))

    fixed = next(block for block in result.sides[0].blocks if block.kind is BlockKind.FILE_HEADER)
    assert int.from_bytes(fixed.payload[0x0D:0x0F], "little") == 4
    assert [action.kind for action in report.actions] == ["file_size"]


def test_trailing_data_is_dropped() -> None:
    disk = patch_side(sample(), sample().sides[0].blocks, tail=b"junk")

    result, report = rebuild(disk)

    assert result.sides[0].tail == b""
    assert [action.kind for action in report.actions] == ["tail"]


def test_trailing_data_can_be_kept() -> None:
    disk = patch_side(sample(), sample().sides[0].blocks, tail=b"junk")

    result, report = rebuild(disk, options=RebuildOptions(keep_tail=True))

    assert result.sides[0].tail == b"junk"
    assert report.actions == ()


def test_hidden_files_survive_by_default() -> None:
    disk = set_file_amount(sample(files=2), 1)

    result, report = rebuild(disk)

    assert result.sides[0].file_count == 2
    assert result.sides[0].hidden_file_count == 1
    assert report.actions == ()


def test_hidden_files_can_be_revealed() -> None:
    disk = set_file_amount(sample(files=2), 1)

    result, report = rebuild(disk, options=RebuildOptions(reveal_hidden=True))

    assert result.sides[0].declared_file_count == 2
    assert result.sides[0].hidden_file_count == 0
    assert [action.kind for action in report.actions] == ["reveal"]


def test_hidden_files_can_be_dropped() -> None:
    disk = set_file_amount(sample(files=2), 1)

    result, report = rebuild(disk, options=RebuildOptions(drop_hidden=True))

    assert result.sides[0].file_count == 1
    assert [action.kind for action in report.actions] == ["drop_hidden"]


def test_dropping_nothing_reports_nothing() -> None:
    result, report = rebuild(sample(files=2), options=RebuildOptions(drop_hidden=True))

    assert result.sides[0].file_count == 2
    assert report.actions == ()


def test_revealing_nothing_reports_nothing() -> None:
    assert actions(sample(files=2), reveal_hidden=True) == ()


def test_revealing_and_dropping_together_is_refused() -> None:
    with pytest.raises(ValueError, match="either reveal or drop"):
        rebuild(sample(), options=RebuildOptions(reveal_hidden=True, drop_hidden=True))


def test_files_can_be_renumbered() -> None:
    disk = sample(files=2)
    headers = [block for block in disk.sides[0].blocks if block.kind is BlockKind.FILE_HEADER]
    payload = bytearray(headers[1].payload)
    payload[1] = 9
    blocks = tuple(
        Block(kind=block.kind, payload=bytes(payload)) if block is headers[1] else block
        for block in disk.sides[0].blocks
    )

    result, report = rebuild(patch_side(disk, blocks), options=RebuildOptions(renumber=True))

    numbers = [header.number for header in result.sides[0].file_headers]
    assert numbers == [0, 1]
    assert [action.kind for action in report.actions] == ["renumber"]


def test_renumbering_an_already_ordered_side_reports_nothing() -> None:
    assert actions(sample(files=2), renumber=True) == ()


def test_an_unformatted_side_is_left_alone() -> None:
    blank, _ = decode(blank_image(sides=1, headered=False, formatted=False))

    result, report = rebuild(blank)

    assert result == blank
    assert report.actions == ()


def test_a_header_without_data_is_left_alone() -> None:
    disk = sample()
    blocks = tuple(block for block in disk.sides[0].blocks if block.kind is not BlockKind.FILE_DATA)

    result, report = rebuild(patch_side(disk, blocks))

    assert report.actions == ()
    assert len(result.sides[0].blocks) == len(blocks)


def test_every_side_is_rebuilt() -> None:
    one = sample().sides[0]
    other = Side(blocks=one.blocks, tail=b"junk", capacity=one.capacity)
    disk = Disk(sides=(one, other))

    _, report = rebuild(disk)

    assert [action.side for action in report.actions] == [1]


def test_a_hidden_header_without_data_is_dropped() -> None:
    disk = set_file_amount(sample(files=1), 0)
    blocks = tuple(block for block in disk.sides[0].blocks if block.kind is not BlockKind.FILE_DATA)

    result, report = rebuild(patch_side(disk, blocks), options=RebuildOptions(drop_hidden=True))

    assert result.sides[0].file_headers == ()
    assert [action.kind for action in report.actions] == ["drop_hidden"]
