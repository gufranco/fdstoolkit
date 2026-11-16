from __future__ import annotations

import hashlib

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.raw import (
    block_pulses,
    block_regions,
    block_starts,
    encode_block_stream,
    pack_raw03,
    unpack_raw03,
)
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Side
from fdstoolkit.drive.sampling import (
    SideSample,
)
from fdstoolkit.edit.files import FileSpec, insert_file

FILES = 4


SKIP_SYNC = 40


NUDGED = 60


TRAILING_GAP = 4000


DIGESTS_PER_FILE = 8


def file_bytes(number: int) -> bytes:
    return b"".join(
        hashlib.sha256(f"file {number} part {part}".encode()).digest()
        for part in range(DIGESTS_PER_FILE)
    )


def reference_side() -> Side:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="CAL"))
    for number in range(FILES):
        disk = insert_file(
            disk,
            side=0,
            spec=FileSpec(
                name=f"FILE{number:04d}",
                address=0x6000,
                kind=FileKind.PROGRAM,
                data=file_bytes(number),
            ),
        )
    return disk.sides[0]


def stream(side: Side, *, keep: slice = slice(None)) -> bytes:
    return encode_block_stream([block.payload for block in side.blocks[keep]])


def nudged(packed: bytes, *, shorter: bool, first: int = 0) -> bytes:
    values = bytearray(unpack_raw03(packed))
    for start in block_starts(bytes(values))[first:]:
        changed = 0
        for index in range(start + SKIP_SYNC, len(values)):
            if changed == NUDGED:
                break
            value = values[index]
            if shorter and value > 0:
                values[index] = value - 1
                changed += 1
            elif not shorter and value < 2:
                values[index] = value + 1
                changed += 1
    return pack_raw03(bytes(values))


class Reader:
    def __init__(self, captures: list[bytes]) -> None:
        self.captures = captures
        self.reads = 0

    def read_raw_side(self, *, what: str) -> bytes:
        del what
        capture = self.captures[min(self.reads, len(self.captures) - 1)]
        self.reads += 1
        return capture


class Interrupted:
    def read_raw_side(self, *, what: str) -> bytes:
        del what
        raise KeyboardInterrupt


def decline(prompt: str) -> bool:
    del prompt
    return False


def noisy_sample(*, invalid: int, leaning: int) -> SideSample:
    return SideSample(
        blocks=(True, False),
        short=leaning,
        long=0,
        invalid=invalid,
        compared=1000,
        referenced=True,
    )


STRAYS = 20


STRAY_SPACING = 40


STRAY_START = 60


DATA_BLOCK = 3


def with_strays(side: Side, *, shift: int, lead: int) -> bytes:
    values = bytearray(unpack_raw03(stream(side)))
    start, _ = block_regions(bytes(values))[DATA_BLOCK]
    for number in range(STRAYS):
        values[start + STRAY_START + number * STRAY_SPACING + shift] = 3
    return pack_raw03(bytes(lead) + bytes(values))


CLOSING_BLOCK = 5


def closing_pulse_read_long(side: Side) -> bytes:
    values = bytearray(unpack_raw03(stream(side)))
    start = block_starts(bytes(values))[CLOSING_BLOCK]
    closing = start + len(block_pulses(side.blocks[CLOSING_BLOCK].payload)) - 1
    values[closing] = 2
    return pack_raw03(bytes(values))
