from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.build.blank import DEFAULT_GAME_NAME, disk_info_block
from fdstoolkit.codecs import fds
from fdstoolkit.core.bitstream import EMULATION_BUFFER, emulated_side_size
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.disk import Disk, Side, require_readable_sides
from fdstoolkit.edit.files import FileSpec, insert_file
from fdstoolkit.hardware.ports import DiskReader, DiskWriter
from fdstoolkit.hardware.session import Grade, dump, write_verified

PATTERNS: Final = (0x00, 0xFF, 0xAA, 0x55)
PATTERN_FILE_SIZE: Final = 4096
PATTERN_NAME: Final = "SURFACE"
SIDE_CAPACITY: Final = fds.SIDE_SIZE
FILE_OVERHEAD: Final = 17
MIN_FILE_SIZE: Final = 64
HARD_FAILURES: Final = 2
BASE_BITSTREAM_COST: Final = 3538 + 58 + 4 + 123
FILE_BITSTREAM_COST: Final = 123 + 18 + 123 + 3
IMAGE_BASE_COST: Final = 58


class SurfaceTestRefusedError(Exception):
    pass


class Finish(StrEnum):
    LEAVE = "leave"
    BLANK = "blank"
    ERASE = "erase"


@dataclass(frozen=True, slots=True)
class SurfacePlan:
    rounds: int = 1
    fill: bool = True
    finish: Finish = Finish.LEAVE
    retries: int = 3


@dataclass(frozen=True, slots=True)
class PatternPass:
    pattern: int
    verified: bool
    mismatched_blocks: tuple[tuple[int, int], ...]
    grade: Grade
    round: int = 1


@dataclass(frozen=True, slots=True)
class SurfaceReport:
    passes: tuple[PatternPass, ...]
    coverage: float = 0.0
    data_bytes: int = 0
    finish: Finish = Finish.LEAVE
    finish_verified: bool = True

    @property
    def failed_patterns(self) -> tuple[int, ...]:
        return tuple(entry.pattern for entry in self.passes if not entry.verified)

    @property
    def failure_counts(self) -> dict[tuple[int, int], int]:
        counts: dict[tuple[int, int], int] = {}
        for entry in self.passes:
            for block in entry.mismatched_blocks:
                counts[block] = counts.get(block, 0) + 1
        return counts

    @property
    def hard_blocks(self) -> tuple[tuple[int, int], ...]:
        counts = self.failure_counts
        return tuple(sorted(b for b, n in counts.items() if n >= HARD_FAILURES))

    @property
    def transient_blocks(self) -> tuple[tuple[int, int], ...]:
        counts = self.failure_counts
        return tuple(sorted(b for b, n in counts.items() if n < HARD_FAILURES))

    @property
    def recovered_blocks(self) -> tuple[tuple[int, int], ...]:
        seen: set[tuple[int, int]] = set()
        last: set[tuple[int, int]] = set()
        for entry in self.passes:
            seen.update(entry.mismatched_blocks)
            last = set(entry.mismatched_blocks)
        return tuple(sorted(seen - last))

    @property
    def grade(self) -> Grade:
        if self.failed_patterns:
            return Grade.FAILED
        grades = {entry.grade for entry in self.passes}
        if Grade.UNSTABLE in grades:
            return Grade.UNSTABLE
        if Grade.MARGINAL in grades:
            return Grade.MARGINAL
        return Grade.CLEAN


def _file_sizes() -> tuple[int, ...]:
    physical = EMULATION_BUFFER - BASE_BITSTREAM_COST
    logical = SIDE_CAPACITY - IMAGE_BASE_COST
    sizes: list[int] = []
    while True:
        room = min(physical - FILE_BITSTREAM_COST, logical - FILE_OVERHEAD)
        if room < MIN_FILE_SIZE:
            break
        size = min(PATTERN_FILE_SIZE, room)
        sizes.append(size)
        physical -= FILE_BITSTREAM_COST + size
        logical -= FILE_OVERHEAD + size
    return tuple(sizes)


def pattern_disk(pattern: int, *, sides: int, fill: bool = True) -> Disk:
    sizes = _file_sizes() if fill else (PATTERN_FILE_SIZE,)
    built: list[Side] = []
    for index in range(sides):
        blocks = (
            Block(
                kind=BlockKind.DISK_INFO,
                payload=disk_info_block(
                    side=index % 2,
                    disk_number=index // 2,
                    game_name="TST",
                ),
            ),
            Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([BlockKind.FILE_AMOUNT, 0])),
        )
        disk = Disk(sides=(Side(blocks=blocks, tail=b"", capacity=SIDE_CAPACITY),))
        for number, size in enumerate(sizes):
            disk = insert_file(
                disk,
                side=0,
                spec=FileSpec(
                    name=f"{PATTERN_NAME}{number:02d}"[:8],
                    address=0x6000,
                    kind=FileKind.PROGRAM,
                    data=bytes([pattern]) * size,
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
                            side=index % 2,
                            disk_number=index // 2,
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


def _confirmation_message(sides: int) -> str:
    return (
        f"a surface test destroys every byte on {sides} side(s) of the disk in the drive. "
        "Use a scratch disk, never an original"
    )


def surface_test(
    writer: DiskWriter,
    reader: DiskReader,
    *,
    sides: int,
    confirm: Callable[[str], bool],
    backup: Callable[[bytes], None] | None = None,
    plan: SurfacePlan | None = None,
) -> SurfaceReport:
    require_readable_sides(sides)
    plan = plan or SurfacePlan()
    rounds, fill, finish, retries = plan.rounds, plan.fill, plan.finish, plan.retries
    if rounds < 1:
        message = "a surface test runs at least one round"
        raise SurfaceTestRefusedError(message)
    status = writer.status()
    if not status.can_write:
        message = f"cannot run a surface test: {', '.join(status.write_blockers)}"
        raise SurfaceTestRefusedError(message)

    if not confirm(_confirmation_message(sides)):
        message = "the operator declined the surface test"
        raise SurfaceTestRefusedError(message)

    if backup is not None:
        original = dump(reader, sides=sides, retries=retries)
        data, _ = fds.encode(original.as_disk(), headered=False)
        backup(data)

    results: list[PatternPass] = []
    written = pattern_disk(PATTERNS[0], sides=sides, fill=fill).sides[0]
    coverage = emulated_side_size(written) / EMULATION_BUFFER
    data_bytes = written.content_size

    for index in range(rounds):
        for pattern in PATTERNS:
            report = write_verified(
                writer,
                reader,
                pattern_disk(pattern, sides=sides, fill=fill),
                confirm=lambda _: True,
                backup=None,
                retries=retries,
                skip_backup=True,
            )
            results.append(
                PatternPass(
                    pattern=pattern,
                    verified=report.verified,
                    mismatched_blocks=report.mismatched_blocks,
                    grade=report.grade,
                    round=index + 1,
                ),
            )

    finished = True
    if finish is not Finish.LEAVE:
        final = blank_disk(sides=sides) if finish is Finish.BLANK else erased_disk(sides=sides)
        finished = write_verified(
            writer,
            reader,
            final,
            confirm=lambda _: True,
            backup=None,
            retries=retries,
            skip_backup=True,
        ).verified

    return SurfaceReport(
        passes=tuple(results),
        coverage=coverage,
        data_bytes=data_bytes,
        finish=finish,
        finish_verified=finished,
    )
