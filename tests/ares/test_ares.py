from __future__ import annotations

from dataclasses import replace

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.ares import (
    ARES_SIDE_SIZE,
    BLOCK_GAP,
    PREGAP,
    decode_side,
    encode_side,
    side_file_names,
    split_for_ares,
)
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.crc import block_crc
from fdstoolkit.core.disk import Disk
from fdstoolkit.edit.files import FileSpec, insert_file


def game(*, sides: int = 1, files: int = 1) -> Disk:
    disk, _ = decode(blank_image(sides=sides, headered=False, formatted=True, game_name="SMB"))
    for side in range(sides):
        for index in range(files):
            disk = insert_file(
                disk,
                side=side,
                spec=FileSpec(
                    name=f"F{index}",
                    address=0x6000,
                    kind=FileKind.PROGRAM,
                    data=bytes([index + 1]) * 8,
                ),
            )
    return disk


def ares_reference(disk: Disk) -> bytes:
    out = bytearray()
    blocks = disk.sides[0].blocks
    for index, block in enumerate(blocks):
        out += bytes(PREGAP if index == 0 else BLOCK_GAP)
        out.append(0x80)
        out += block.payload
        out += block_crc(block.payload).to_bytes(2, "little")
    return bytes(out).ljust(ARES_SIDE_SIZE, b"\0")


def test_a_side_is_laid_out_the_way_ares_writes_it() -> None:
    disk = game()

    assert encode_side(disk.sides[0]) == ares_reference(disk)


def test_every_side_file_is_the_size_ares_expects() -> None:
    assert len(encode_side(game().sides[0])) == ARES_SIDE_SIZE


def test_the_files_are_named_the_way_ares_names_them() -> None:
    assert side_file_names(4) == ("disk1.sideA", "disk1.sideB", "disk2.sideA", "disk2.sideB")


def test_a_side_with_no_file_is_refused_as_ares_refuses_it() -> None:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True))

    with pytest.raises(ValueError, match="at least one file"):
        encode_side(disk.sides[0])


def test_an_unformatted_side_is_refused() -> None:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=False))

    with pytest.raises(ValueError, match="at least one file"):
        encode_side(disk.sides[0])


def test_decoding_returns_the_blocks() -> None:
    disk = game(files=2)

    side = decode_side(encode_side(disk.sides[0]))

    assert [block.payload for block in side.blocks] == [
        block.payload for block in disk.sides[0].blocks
    ]


def test_decoding_keeps_the_stored_checksums() -> None:
    side = decode_side(encode_side(game().sides[0]))

    assert all(block.stored_crc == block.computed_crc for block in side.blocks)


def test_a_damaged_checksum_survives_decoding_as_a_mismatch() -> None:
    raw = bytearray(encode_side(game().sides[0]))
    raw[PREGAP + 1 + 56] ^= 0xFF

    side = decode_side(bytes(raw))

    assert side.blocks[0].stored_crc != side.blocks[0].computed_crc


def test_a_file_of_the_wrong_size_is_refused() -> None:
    with pytest.raises(ValueError, match=str(ARES_SIDE_SIZE)):
        decode_side(bytes(100))


def test_a_block_running_past_the_end_ends_the_side() -> None:
    raw = bytearray(encode_side(game().sides[0]))
    used = PREGAP + 1 + 56 + 2 + BLOCK_GAP + 1 + 2 + 2
    raw[used:] = bytes(ARES_SIDE_SIZE - used)
    raw[ARES_SIDE_SIZE - 5] = 0x80
    raw[ARES_SIDE_SIZE - 4] = 0x03

    side = decode_side(bytes(raw))

    assert len(side.blocks) == 2


def test_a_side_with_no_sync_mark_is_empty() -> None:
    side = decode_side(bytes(ARES_SIDE_SIZE))

    assert side.blocks == ()


def test_an_unknown_block_code_ends_the_side() -> None:
    raw = bytearray(encode_side(game().sides[0]))
    raw[PREGAP + 1] = 0x07

    assert decode_side(bytes(raw)).blocks == ()


def test_a_whole_image_splits_into_named_side_files() -> None:
    files = split_for_ares(game(sides=2))

    assert list(files) == ["disk1.sideA", "disk1.sideB"]
    assert all(len(data) == ARES_SIDE_SIZE for data in files.values())


def test_decoding_a_side_rebuilds_a_side_the_fds_codec_accepts() -> None:
    disk = game(files=3)

    side = decode_side(encode_side(disk.sides[0]))

    assert side.file_count == 3
    assert side.declared_file_count == 3


def test_a_stray_block_after_the_files_ends_what_ares_writes() -> None:
    side = game().sides[0]
    stray = Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([0x02, 0x00]))
    extended = replace(side, blocks=(*side.blocks, stray))

    assert encode_side(extended) == encode_side(side)


def test_a_side_too_large_for_an_ares_file_is_refused() -> None:
    side = game().sides[0]
    huge = Block(kind=BlockKind.FILE_DATA, payload=bytes([0x04]) + bytes(ARES_SIDE_SIZE))
    oversized = replace(side, blocks=(*side.blocks[:3], huge))

    with pytest.raises(ValueError, match="an ares side holds"):
        encode_side(oversized)
