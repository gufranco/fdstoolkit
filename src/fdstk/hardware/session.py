from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from fdstk.codecs import fds
from fdstk.core.blocks import Block, BlockKind
from fdstk.core.disk import Disk, Side
from fdstk.hardware.ports import BlockRead, DiskReader, DiskWriter, HardwareFaultError

DEFAULT_RETRIES = 3
MIN_PASSES = 2


class Grade(StrEnum):
    CLEAN = "clean"
    MARGINAL = "marginal"
    UNSTABLE = "unstable"
    FAILED = "failed"


class WriteRefusedError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SideDump:
    index: int
    blocks: tuple[BlockRead, ...]

    @property
    def marginal_blocks(self) -> tuple[int, ...]:
        return tuple(block.index for block in self.blocks if block.is_marginal)

    @property
    def failed_blocks(self) -> tuple[int, ...]:
        return tuple(block.index for block in self.blocks if block.failed)

    @property
    def grade(self) -> Grade:
        if self.failed_blocks:
            return Grade.FAILED
        if self.marginal_blocks:
            return Grade.MARGINAL
        return Grade.CLEAN

    def as_side(self, capacity: int) -> Side:
        return Side(
            blocks=tuple(
                Block(kind=BlockKind(block.payload[0]), payload=block.payload, stored_crc=None)
                for block in self.blocks
            ),
            tail=b"",
            capacity=capacity,
        )


@dataclass(frozen=True, slots=True)
class DumpResult:
    sides: tuple[SideDump, ...]

    @property
    def grade(self) -> Grade:
        grades = {side.grade for side in self.sides}
        for candidate in (Grade.FAILED, Grade.MARGINAL):
            if candidate in grades:
                return candidate
        return Grade.CLEAN

    def as_disk(self, capacity: int = fds.SIDE_SIZE) -> Disk:
        return Disk(sides=tuple(side.as_side(capacity) for side in self.sides))


@dataclass(frozen=True, slots=True)
class StabilityReport:
    passes: tuple[DumpResult, ...]
    unstable_blocks: tuple[tuple[int, int], ...]

    @property
    def grade(self) -> Grade:
        if self.unstable_blocks:
            return Grade.UNSTABLE
        return max(
            (result.grade for result in self.passes),
            key=lambda grade: (grade is Grade.FAILED, grade is Grade.MARGINAL),
        )


@dataclass(frozen=True, slots=True)
class WriteReport:
    verified: bool
    mismatched_blocks: tuple[tuple[int, int], ...]
    dump: DumpResult

    @property
    def grade(self) -> Grade:
        if not self.verified or self.mismatched_blocks:
            return Grade.FAILED
        return self.dump.grade


def _require_readable(reader: DiskReader) -> None:
    status = reader.status()
    if not status.can_read:
        message = f"cannot read: {', '.join(status.blockers)}"
        raise WriteRefusedError(message)


def _read_block_with_retries(
    reader: DiskReader,
    side: int,
    index: int,
    first: BlockRead,
    retries: int,
) -> BlockRead:
    if first.crc_ok or retries <= 1:
        return first
    attempts = 1
    latest = first
    while attempts < retries and not latest.crc_ok:
        attempts += 1
        again = list(reader.read_side(side))
        if index >= len(again):
            break
        latest = again[index]
    return BlockRead(
        index=index,
        payload=latest.payload,
        crc_ok=latest.crc_ok,
        attempts=attempts,
    )


def dump(reader: DiskReader, *, sides: int, retries: int = DEFAULT_RETRIES) -> DumpResult:
    _require_readable(reader)
    dumped: list[SideDump] = []
    for side in range(sides):
        first_pass = list(reader.read_side(side))
        blocks = tuple(
            _read_block_with_retries(reader, side, index, block, retries)
            for index, block in enumerate(first_pass)
        )
        dumped.append(SideDump(index=side, blocks=blocks))
    return DumpResult(sides=tuple(dumped))


def dump_repeated(
    reader: DiskReader,
    *,
    sides: int,
    passes: int = MIN_PASSES,
    retries: int = DEFAULT_RETRIES,
) -> StabilityReport:
    if passes < MIN_PASSES:
        message = f"a stability check needs at least two passes, got {passes}"
        raise ValueError(message)

    results = tuple(dump(reader, sides=sides, retries=retries) for _ in range(passes))
    unstable: list[tuple[int, int]] = []
    first = results[0]
    for side_index, side in enumerate(first.sides):
        for block in side.blocks:
            payloads = {
                other.sides[side_index].blocks[block.index].payload
                for other in results
                if block.index < len(other.sides[side_index].blocks)
            }
            if len(payloads) > 1:
                unstable.append((side_index, block.index))
    return StabilityReport(passes=results, unstable_blocks=tuple(unstable))


def _compare(disk: Disk, readback: DumpResult) -> tuple[tuple[int, int], ...]:
    mismatched: list[tuple[int, int]] = []
    for side_index, side in enumerate(disk.sides):
        written = readback.sides[side_index].blocks
        for block_index, block in enumerate(side.blocks):
            if block_index >= len(written) or written[block_index].payload != block.payload:
                mismatched.append((side_index, block_index))
    return tuple(mismatched)


def _take_backup(
    reader: DiskReader,
    disk: Disk,
    backup: Callable[[bytes], None] | None,
    retries: int,
) -> None:
    original = dump(reader, sides=disk.side_count, retries=retries)
    if backup is not None:
        data, _ = fds.encode(original.as_disk(), headered=False)
        backup(data)


def _confirmation_message(disk: Disk) -> str:
    return (
        f"overwrite the disk in the drive with {disk.side_count} side(s) of new data, "
        "destroying whatever it holds now"
    )


def write_verified(
    writer: DiskWriter,
    reader: DiskReader,
    disk: Disk,
    *,
    confirm: Callable[[str], bool],
    backup: Callable[[bytes], None] | None,
    retries: int = DEFAULT_RETRIES,
    skip_backup: bool = False,
) -> WriteReport:
    status = writer.status()
    if not status.can_write:
        message = f"cannot write: {', '.join(status.blockers)}"
        raise WriteRefusedError(message)

    present = dump(reader, sides=1, retries=retries)
    if disk.side_count > len(present.sides) and disk.side_count > 1:
        message = (
            f"the image has {disk.side_count} side(s); write them one side at a time, "
            "flipping the disk between writes"
        )
        raise WriteRefusedError(message)

    if not skip_backup:
        _take_backup(reader, disk, backup, retries)

    if not confirm(_confirmation_message(disk)):
        message = "the operator declined the write"
        raise WriteRefusedError(message)

    for index, side in enumerate(disk.sides):
        payloads = [block.payload for block in side.blocks]
        try:
            writer.write_side(index, payloads)
        except HardwareFaultError as fault:
            message = f"the write stopped at side {index}: {fault}"
            raise WriteRefusedError(message) from fault

    readback = dump(reader, sides=disk.side_count, retries=retries)
    mismatched = _compare(disk, readback)

    return WriteReport(
        verified=not mismatched,
        mismatched_blocks=tuple(mismatched),
        dump=readback,
    )
