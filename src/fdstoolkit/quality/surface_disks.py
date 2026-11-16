from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Final

from fdstoolkit.build.blank import DEFAULT_GAME_NAME, disk_info_block
from fdstoolkit.build.calibration import (
    FILE_SIZE,
    FILES_PER_SIDE,
    Pattern,
    pattern_bytes,
)
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.disk import SIDE_SIZE, Disk, Side
from fdstoolkit.edit.files import DEFAULT_LOAD_ADDRESS, FileSpec, insert_file

QUICK_FILE_SIZE: Final = 4096


PATTERN_NAME: Final = "SURFACE"


SIDE_CAPACITY: Final = SIDE_SIZE


class SurfacePattern(StrEnum):
    UNIQUE = "unique data"
    SHORT = "short pulses"
    MEDIUM = "medium pulses"
    LONG = "long pulses"


PATTERNS: Final = tuple(SurfacePattern)


FIXED: Final[dict[SurfacePattern, Pattern]] = {
    SurfacePattern.SHORT: Pattern.SHORT,
    SurfacePattern.MEDIUM: Pattern.MEDIUM,
    SurfacePattern.LONG: Pattern.LONG,
}


def _file_sizes(*, fill: bool) -> tuple[int, ...]:
    return (FILE_SIZE,) * FILES_PER_SIDE if fill else (QUICK_FILE_SIZE,)


def _data(pattern: SurfacePattern, *, key: bytes, side: int, number: int, size: int) -> bytes:
    fixed = FIXED.get(pattern)
    if fixed is not None:
        return pattern_bytes(fixed, size)
    return hashlib.shake_256(key + bytes([side, number])).digest(size)


def pattern_disk(
    pattern: SurfacePattern, *, sides: int, fill: bool = True, key: bytes = b""
) -> Disk:
    built: list[Side] = []
    for index in range(sides):
        blocks = (
            Block(
                kind=BlockKind.DISK_INFO,
                payload=disk_info_block(
                    side=index,
                    disk_number=0,
                    game_name="TST",
                ),
            ),
            Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([BlockKind.FILE_AMOUNT, 0])),
        )
        disk = Disk(sides=(Side(blocks=blocks, tail=b"", capacity=SIDE_CAPACITY),))
        for number, size in enumerate(_file_sizes(fill=fill)):
            disk = insert_file(
                disk,
                side=0,
                spec=FileSpec(
                    name=f"{PATTERN_NAME}{number:02d}"[:8],
                    address=DEFAULT_LOAD_ADDRESS,
                    kind=FileKind.PROGRAM,
                    data=_data(pattern, key=key, side=index, number=number, size=size),
                ),
            )
        built.append(disk.sides[0])
    return Disk(sides=tuple(built))


def blank_disk(*, sides: int, game_name: str = DEFAULT_GAME_NAME) -> Disk:
    return Disk(
        sides=tuple(
            Side(
                blocks=(
                    Block(
                        kind=BlockKind.DISK_INFO,
                        payload=disk_info_block(
                            side=index,
                            disk_number=0,
                            game_name=game_name,
                        ),
                    ),
                    Block(
                        kind=BlockKind.FILE_AMOUNT,
                        payload=bytes([BlockKind.FILE_AMOUNT, 0]),
                    ),
                ),
                tail=b"",
                capacity=SIDE_CAPACITY,
            )
            for index in range(sides)
        ),
    )


def erased_disk(*, sides: int) -> Disk:
    return Disk(
        sides=tuple(Side(blocks=(), tail=b"", capacity=SIDE_CAPACITY) for _ in range(sides)),
    )
