from __future__ import annotations

import hashlib
from typing import Final

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs import fds
from fdstoolkit.codecs.raw import block_regions, encode_block_stream, pack_raw03, unpack_raw03
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Disk
from fdstoolkit.drive.captures import Capture, bundle_zip
from fdstoolkit.edit.files import FileSpec, insert_file

DAMAGED: Final = 3
TRAILING_GAP: Final = 4000
SKIP_SYNC: Final = 40
CREATED: Final = "2026-09-25T12:00:00Z"
IMAGE: Final = "game.fds"


def disk_with_a_file() -> Disk:
    disk, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True, game_name="CAP"))
    return insert_file(
        disk,
        side=0,
        spec=FileSpec(
            name="FILE0000",
            address=0x6000,
            kind=FileKind.PROGRAM,
            data=hashlib.sha256(b"captures").digest() * 8,
        ),
    )


def read_of(disk: Disk, offset: int | None) -> bytes:
    values = bytearray(unpack_raw03(encode_block_stream([b.payload for b in disk.sides[0].blocks])))
    if offset is not None:
        start, _ = block_regions(bytes(values))[DAMAGED]
        position = start + SKIP_SYNC + offset
        values[position] = 1 if values[position] == 0 else 0
    return pack_raw03(bytes(values) + bytes(TRAILING_GAP))


def captures_of(disk: Disk, offsets: tuple[int | None, ...]) -> tuple[Capture, ...]:
    return tuple(
        Capture(side=0, read=number, data=read_of(disk, offset))
        for number, offset in enumerate(offsets, start=1)
    )


def zipped(disk: Disk, offsets: tuple[int | None, ...]) -> bytes:
    return bundle_zip(captures_of(disk, offsets), image=IMAGE, created=CREATED)


def image_of(disk: Disk) -> bytes:
    data, _ = fds.encode(disk, headered=False)
    return data
