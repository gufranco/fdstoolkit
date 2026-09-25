from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from functools import cache
from typing import Final

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs import fds
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.disk import SIDES_PER_DISK, Disk, Side
from fdstoolkit.drive.align import good_block
from fdstoolkit.edit.files import FileSpec, insert_file

CALIBRATION_GAME: Final = "CAL"
FILE_SIZE: Final = 8949
LOAD_ADDRESS: Final = 0x6000
FACTORY_P95_SIDE: Final = 53_910
LARGEST_FACTORY_SIDE: Final = 54_958

LONG_BYTE: Final = 0xAA
MEDIUM_BYTES: Final = bytes([0x24, 0x49, 0x92])
SHORT_BYTE: Final = 0x00
MIXED_RUN: Final = 48
MIXED_SHORT_RUN: Final = 16


class Pattern(StrEnum):
    LONG = "LNG"
    MEDIUM = "MED"
    MIXED = "MIX"


LAYOUT: Final = (
    Pattern.LONG,
    Pattern.MEDIUM,
    Pattern.MIXED,
    Pattern.LONG,
    Pattern.MEDIUM,
    Pattern.MIXED,
)
FILES_PER_SIDE: Final = len(LAYOUT)

TRUSTED_DRIVE: Final = (
    (
        "Write this disk only on a drive you already trust. A drive out of adjustment "
        "writes a disk that reads back on it and on nothing else, so this disk would "
        "teach every other drive that drive's error."
    ),
    "Clean the read head first: contamination reads as a media fault.",
    (
        "Put the spindle hub back at its factory position, set with a 1.5 mm hex screw; "
        "misplaced, it gives errors 22 and 27 (famicomdisksystem.com)."
    ),
    (
        "Set the read head. Its far edge is published as 35.5 mm from the spindle "
        "centre, tolerance about 0.05 mm (TinkerDifferent). Use calibrate head --bracket "
        "on a factory disk and settle in the middle of the range that reads."
    ),
    "Set the motor speed with calibrate speed on a factory disk until it reads clean.",
    (
        "Finish the speed on a console: Copy Master's speed test should show 5 with a "
        "disk in the drive, run twice (ToToTEK and Bung). A strobe at the disk table "
        "shaft is the alternative, 400 RPM in one guide."
    ),
    (
        "Confirm on three factory disks, every side, several passes: a head can be set "
        "to suit one disk and miss another."
    ),
    "After writing, read this disk on a second drive before trusting it.",
)


def _pattern_bytes(pattern: Pattern) -> bytes:
    if pattern is Pattern.LONG:
        return bytes([LONG_BYTE]) * FILE_SIZE
    if pattern is Pattern.MEDIUM:
        return (MEDIUM_BYTES * (FILE_SIZE // len(MEDIUM_BYTES) + 1))[:FILE_SIZE]
    cycle = (
        bytes([LONG_BYTE]) * MIXED_RUN
        + MEDIUM_BYTES * (MIXED_RUN // len(MEDIUM_BYTES))
        + bytes([SHORT_BYTE]) * MIXED_SHORT_RUN
    )
    return (cycle * (FILE_SIZE // len(cycle) + 1))[:FILE_SIZE]


def pattern_of(payload: bytes) -> Pattern | None:
    data = payload[1:]
    return next((pattern for pattern in Pattern if _pattern_bytes(pattern) == data), None)


def _file_name(pattern: Pattern, index: int) -> str:
    return f"CAL-{pattern.value}{index // len(Pattern) + 1}"


@cache
def calibration_disk(sides: int = SIDES_PER_DISK) -> Disk:
    disk, _ = fds.decode(
        blank_image(sides=sides, headered=False, formatted=True, game_name=CALIBRATION_GAME)
    )
    for side in range(sides):
        for index, pattern in enumerate(LAYOUT):
            disk = insert_file(
                disk,
                side=side,
                spec=FileSpec(
                    name=_file_name(pattern, index),
                    address=LOAD_ADDRESS,
                    kind=FileKind.PROGRAM,
                    data=_pattern_bytes(pattern),
                ),
            )
    return disk


def calibration_image(*, headered: bool, sides: int = SIDES_PER_DISK) -> bytes:
    data, _ = fds.encode(calibration_disk(sides), headered=headered)
    return data


SIDE_PAYLOAD: Final = sum(len(block.payload) for block in calibration_disk().sides[0].blocks)


def matching_side(blocks: Sequence[Block]) -> Side | None:
    readable = [block for block in blocks if block.stored_crc is None or good_block(block)]
    infos = {block.payload for block in readable if block.kind is BlockKind.DISK_INFO}
    headers = {block.payload for block in readable if block.kind is BlockKind.FILE_HEADER}
    for side in calibration_disk().sides:
        if side.blocks[0].payload not in infos:
            continue
        expected = {block.payload for block in side.blocks if block.kind is BlockKind.FILE_HEADER}
        if expected & headers:
            return side
    return None


DECIDES_ITSELF: Final = "the calibration disk decides its own sides, format and game name"


class CalibrationChoiceError(ValueError):
    pass


def check_write_choice(*, has_image: bool, calibration: bool, trusted_drive: bool) -> None:
    if has_image and calibration:
        message = "write takes an image or the calibration disk, not both"
        raise CalibrationChoiceError(message)
    if not has_image and not calibration:
        message = "write takes an image or the calibration disk, one of the two"
        raise CalibrationChoiceError(message)
    if has_image and trusted_drive:
        message = "the trusted drive confirmation only applies to the calibration disk"
        raise CalibrationChoiceError(message)
    if calibration and not trusted_drive:
        message = (
            "writing the calibration disk needs the trusted drive confirmation, given only "
            "when every step listed is done on the drive in use"
        )
        raise CalibrationChoiceError(message)
