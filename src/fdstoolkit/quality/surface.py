from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from fdstoolkit.build.blank import disk_info_block
from fdstoolkit.codecs import fds
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.edit.files import FileSpec, insert_file
from fdstoolkit.hardware.ports import DiskReader, DiskWriter
from fdstoolkit.hardware.session import Grade, dump, write_verified

PATTERNS: Final = (0x00, 0xFF, 0xAA, 0x55)
PATTERN_FILE_SIZE: Final = 4096
PATTERN_NAME: Final = "SURFACE"
SIDE_CAPACITY: Final = fds.SIDE_SIZE


class SurfaceTestRefusedError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PatternPass:
    pattern: int
    verified: bool
    mismatched_blocks: tuple[tuple[int, int], ...]
    grade: Grade


@dataclass(frozen=True, slots=True)
class SurfaceReport:
    passes: tuple[PatternPass, ...]

    @property
    def failed_patterns(self) -> tuple[int, ...]:
        return tuple(entry.pattern for entry in self.passes if not entry.verified)

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


def pattern_disk(pattern: int, *, sides: int) -> Disk:
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
        disk = insert_file(
            Disk(sides=(Side(blocks=blocks, tail=b"", capacity=SIDE_CAPACITY),)),
            side=0,
            spec=FileSpec(
                name=PATTERN_NAME,
                address=0x6000,
                kind=FileKind.PROGRAM,
                data=bytes([pattern]) * PATTERN_FILE_SIZE,
            ),
        )
        built.append(disk.sides[0])
    return Disk(sides=tuple(built))


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
    retries: int = 3,
) -> SurfaceReport:
    status = writer.status()
    if not status.can_write:
        message = f"cannot run a surface test: {', '.join(status.blockers)}"
        raise SurfaceTestRefusedError(message)

    if not confirm(_confirmation_message(sides)):
        message = "the operator declined the surface test"
        raise SurfaceTestRefusedError(message)

    if backup is not None:
        original = dump(reader, sides=sides, retries=retries)
        data, _ = fds.encode(original.as_disk(), headered=False)
        backup(data)

    results: list[PatternPass] = []
    for pattern in PATTERNS:
        report = write_verified(
            writer,
            reader,
            pattern_disk(pattern, sides=sides),
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
            ),
        )

    return SurfaceReport(passes=tuple(results))
