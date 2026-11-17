from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.build.blank import disk_info_block
from fdstoolkit.build.calibration import LARGEST_FACTORY_SIDE
from fdstoolkit.codecs import fds
from fdstoolkit.codecs.raw import (
    DECODED,
    GAP_VALUE,
    MARK_GAP_BITS,
    MIN_GAP_VALUES,
    SYNC_MARK,
    SYNC_VALUE,
    UNCLASSED,
    block_regions,
    unpack_detected,
)
from fdstoolkit.core.bitstream import BITS_PER_BYTE
from fdstoolkit.core.blocks import (
    DISK_INFO_SIZE,
    TEST_BLOCK_CODE,
    TEST_PATTERN,
    BlockKind,
)
from fdstoolkit.core.disk import SIDE_SIZE, Disk
from fdstoolkit.hardware.refresh import RefreshDrive
from fdstoolkit.hardware.session import (
    Progress,
    SideDump,
    WriteRefusedError,
    ask_for_flip,
    quiet,
    read_side_with_retries,
)

CHECKER_GAME: Final = "CHK"
EMPTY_AMOUNT: Final = bytes([BlockKind.FILE_AMOUNT, 0])
CHECKER_BYTES: Final = (
    (LARGEST_FACTORY_SIDE - DISK_INFO_SIZE - len(EMPTY_AMOUNT) - 1) // len(TEST_PATTERN)
) * len(TEST_PATTERN)
EXPECTED: Final = (TEST_PATTERN * (CHECKER_BYTES // len(TEST_PATTERN)))[:CHECKER_BYTES]
DECLINED: Final = "the operator declined the write"
CHECKER_ALONE: Final = "the checker pattern takes no --passes, --quick or --finish"


class SurfaceKind(StrEnum):
    CYCLE = "cycle"
    CHECKER = "checker"


@dataclass(frozen=True, slots=True)
class CheckerReading:
    side: int
    matched: int
    expected: int
    found: bool

    @property
    def verified(self) -> bool:
        return self.found and self.matched == self.expected

    def render(self) -> str:
        if not self.found:
            return "no type 5 test block read back"
        if self.verified:
            return f"side {self.side}: all {self.expected} pattern bytes read back"
        return (
            f"side {self.side}: {self.matched} of {self.expected} pattern bytes read back before "
            "the first that differs"
        )


def checker_payloads(side: int) -> tuple[bytes, ...]:
    info = disk_info_block(side=side, disk_number=0, game_name=CHECKER_GAME)
    return (info, EMPTY_AMOUNT, bytes([TEST_BLOCK_CODE]) + EXPECTED)


def _test_block_start(values: bytes) -> int | None:
    regions = block_regions(values)
    zeros = 0
    for index in range(regions[-1][1] if regions else 0, len(values)):
        if values[index] == GAP_VALUE:
            zeros += 1
            continue
        if values[index] == SYNC_VALUE and zeros >= MIN_GAP_VALUES:
            return index
        zeros = 0
    return None


def _decoded(values: bytes, start: int, length: int) -> bytes:
    bits = [0] * MARK_GAP_BITS
    previous = 0
    wanted = (length + 2) * BITS_PER_BYTE
    for value in values[start:]:
        if len(bits) >= wanted:
            break
        added, previous = DECODED.get((previous << 4) | value, UNCLASSED)
        bits += added
    whole = len(bits) // BITS_PER_BYTE
    return bytes(
        sum(
            bit << place
            for place, bit in enumerate(bits[at * BITS_PER_BYTE : (at + 1) * BITS_PER_BYTE])
        )
        for at in range(whole)
    )


def _prefix(found: bytes, wanted: bytes) -> int:
    return next(
        (
            index
            for index, (have, want) in enumerate(zip(found, wanted, strict=False))
            if have != want
        ),
        min(len(found), len(wanted)),
    )


def checker_reading(values: bytes, side: int = 0) -> CheckerReading:
    start = _test_block_start(values)
    if start is None:
        return CheckerReading(side=side, matched=0, expected=CHECKER_BYTES, found=False)
    data = _decoded(values, start, CHECKER_BYTES)
    if data[:2] != bytes([SYNC_MARK, TEST_BLOCK_CODE]):
        return CheckerReading(side=side, matched=0, expected=CHECKER_BYTES, found=False)
    matched = _prefix(data[2:], EXPECTED)
    return CheckerReading(side=side, matched=matched, expected=CHECKER_BYTES, found=True)


def _checked_side(
    drive: RefreshDrive, side: int, keep: Callable[[bytes], None], progress: Progress
) -> CheckerReading:
    progress(f"reading side {side} before writing it")
    before = SideDump(index=side, blocks=read_side_with_retries(drive, side, 0))
    data, _ = fds.encode(Disk(sides=(before.as_side(SIDE_SIZE),)), headered=False)
    keep(data)
    progress(f"writing the checker pattern to side {side}")
    drive.write_side(side, checker_payloads(side))
    progress(f"reading side {side} back")
    list(drive.read_side(side))
    return checker_reading(unpack_detected(drive.captures[-1].data), side)


def run_checker(
    drive: RefreshDrive,
    *,
    sides: int,
    confirm: Callable[[str], bool],
    flip: Callable[[str], bool],
    keep: Callable[[bytes], None],
    progress: Progress = quiet,
) -> tuple[CheckerReading, ...]:
    status = drive.status()
    if not status.can_write:
        message = f"cannot write: {', '.join(status.blockers)}"
        raise WriteRefusedError(message)
    if not confirm(f"the checker pattern destroys every byte on {sides} side(s) of the disk"):
        raise WriteRefusedError(DECLINED)
    readings: list[CheckerReading] = []
    for side in range(sides):
        if side:
            ask_for_flip(drive, side, flip)
        readings.append(_checked_side(drive, side, keep, progress))
    return tuple(readings)
