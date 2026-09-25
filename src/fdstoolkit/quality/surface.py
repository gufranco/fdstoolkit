from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from fdstoolkit.build.blank import DEFAULT_GAME_NAME, disk_info_block
from fdstoolkit.build.calibration import (
    FILE_SIZE,
    FILES_PER_SIDE,
    LARGEST_FACTORY_SIDE,
    Pattern,
    pattern_bytes,
)
from fdstoolkit.codecs import fds
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.disk import Disk, Side, require_readable_sides
from fdstoolkit.drive.captures import latest_capture
from fdstoolkit.drive.monitor import SpeedReading, lean, sample
from fdstoolkit.edit.files import FileSpec, insert_file
from fdstoolkit.hardware.ports import DiskReader, DiskWriter, selects_sides
from fdstoolkit.hardware.session import (
    Grade,
    Progress,
    SideDump,
    SideWrite,
    WriteNotTakenError,
    ask_for_flip,
    refuse_unturned,
    write_side_verified,
)

QUICK_FILE_SIZE: Final = 4096
PATTERN_NAME: Final = "SURFACE"
SIDE_CAPACITY: Final = fds.SIDE_SIZE
HARD_FAILURES: Final = 2
KEY_BYTES: Final = 16


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


class SurfaceTestRefusedError(Exception):
    pass


class StopReason(StrEnum):
    DAMAGED = "a block failed on two patterns, so the surface is damaged"
    REFUSED = "the disk did not take a write, so every further pass would only wear it"


class Finish(StrEnum):
    LEAVE = "leave"
    BLANK = "blank"
    ERASE = "erase"


PULSE_VERDICTS: Final[dict[SpeedReading, str]] = {
    SpeedReading.FAST: "they lean short, which is the drive running fast rather than the surface",
    SpeedReading.SLOW: "they lean long, which is the drive running slow rather than the surface",
    SpeedReading.ERRORS: "they go both ways, which is the surface rather than the drive's speed",
}


@dataclass(frozen=True, slots=True)
class SurfacePlan:
    rounds: int = 1
    fill: bool = True
    finish: Finish = Finish.LEAVE
    retries: int = 3
    key: bytes | None = None


@dataclass(frozen=True, slots=True)
class PatternPass:
    pattern: SurfacePattern
    verified: bool
    mismatched_blocks: tuple[tuple[int, int], ...]
    grade: Grade
    round: int = 1
    side: int = 0
    short: int = 0
    long: int = 0
    compared: int = 0


@dataclass(frozen=True, slots=True)
class SurfaceReport:
    passes: tuple[PatternPass, ...]
    coverage: float = 0.0
    data_bytes: int = 0
    finish: Finish = Finish.LEAVE
    finish_verified: bool = True
    finish_ran: bool = False
    stopped: StopReason | None = None
    refusal: str = ""

    @property
    def passed(self) -> bool:
        return self.grade is Grade.CLEAN and self.finish_verified

    @property
    def failed_patterns(self) -> tuple[SurfacePattern, ...]:
        return tuple(entry.pattern for entry in self.passes if not entry.verified)

    @property
    def pulse_summary(self) -> str:
        reading = self.pulse_reading
        if reading is None:
            return ""
        failed = [entry for entry in self.passes if not entry.verified]
        short = sum(entry.short for entry in failed)
        long = sum(entry.long for entry in failed)
        return (
            f"in the blocks that failed, {short} read short and {long} read long: "
            f"{PULSE_VERDICTS[reading]}"
        )

    @property
    def pulse_reading(self) -> SpeedReading | None:
        failed = [entry for entry in self.passes if not entry.verified and entry.compared]
        if not failed:
            return None
        return lean(sum(entry.short for entry in failed), sum(entry.long for entry in failed))

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
        if self.stopped is not None or self.failed_patterns:
            return Grade.FAILED
        grades = {entry.grade for entry in self.passes}
        if Grade.UNSTABLE in grades:
            return Grade.UNSTABLE
        if Grade.MARGINAL in grades:
            return Grade.MARGINAL
        return Grade.CLEAN


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
                    address=0x6000,
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


def _no_passes() -> list[PatternPass]:
    return []


def _no_sides() -> list[SideDump]:
    return []


@dataclass(slots=True)
class _Run:
    writer: DiskWriter
    reader: DiskReader
    plan: SurfacePlan
    sides: int
    backup: Callable[[bytes], None] | None
    flip: Callable[[str], bool] | None
    progress: Progress
    results: list[PatternPass] = field(default_factory=_no_passes)
    originals: list[SideDump] = field(default_factory=_no_sides)
    last: SideDump | None = None

    def turn_to(self, side: int) -> None:
        ask_for_flip(self.reader, side, self.flip)

    def write(self, index: int, side: Side, *, keep: bool) -> SideWrite:
        def check(present: SideDump) -> None:
            refuse_unturned(self.reader, present, self.last if keep else None)
            if keep:
                self.originals.append(present)
                if self.backup is not None:
                    disk = Disk(sides=tuple(item.as_side(SIDE_CAPACITY) for item in self.originals))
                    data, _ = fds.encode(disk, headered=False)
                    self.backup(data)

        result = write_side_verified(
            self.writer,
            self.reader,
            index,
            side,
            retries=self.plan.retries,
            before_write=check,
        )
        self.last = result.after
        return result


def _misreads(run: _Run, side: int, target: Side, *, failed: bool) -> tuple[int, int, int]:
    packed = latest_capture(run.reader, side) if failed else None
    if packed is None:
        return 0, 0, 0
    found = sample(packed, target)
    return found.short, found.long, found.compared


def _run_patterns(run: _Run) -> tuple[StopReason | None, str]:
    failures: dict[tuple[int, int], int] = {}
    for side_index in range(run.sides):
        if side_index:
            run.turn_to(side_index)
        for index in range(run.plan.rounds):
            key = run.plan.key or secrets.token_bytes(KEY_BYTES)
            for position, pattern in enumerate(PATTERNS):
                run.progress(f"side {side_index} pass {index + 1} pattern {pattern}")
                target = pattern_disk(pattern, sides=run.sides, fill=run.plan.fill, key=key).sides[
                    side_index
                ]
                keep = not index and not position
                try:
                    result = run.write(side_index, target, keep=keep)
                except WriteNotTakenError as refused:
                    return StopReason.REFUSED, str(refused)
                blocks = tuple((side_index, block) for block in result.mismatched)
                short, long, compared = _misreads(run, side_index, target, failed=bool(blocks))
                run.results.append(
                    PatternPass(
                        pattern=pattern,
                        verified=not result.mismatched,
                        mismatched_blocks=blocks,
                        grade=Grade.FAILED if result.mismatched else result.after.grade,
                        round=index + 1,
                        side=side_index,
                        short=short,
                        long=long,
                        compared=compared,
                    ),
                )
                for block in blocks:
                    failures[block] = failures.get(block, 0) + 1
                if any(count >= HARD_FAILURES for count in failures.values()):
                    return StopReason.DAMAGED, ""
    return None, ""


def _finish(run: _Run, finish: Finish) -> bool:
    final = blank_disk(sides=run.sides) if finish is Finish.BLANK else erased_disk(sides=run.sides)
    order = tuple(reversed(range(run.sides)))
    try:
        for position, side_index in enumerate(order):
            if position:
                run.turn_to(side_index)
            run.progress(f"finishing side {side_index}")
            if run.write(side_index, final.sides[side_index], keep=False).mismatched:
                return False
    except WriteNotTakenError:
        return False
    return True


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
    flip: Callable[[str], bool] | None = None,
    progress: Progress = lambda _: None,
) -> SurfaceReport:
    require_readable_sides(sides)
    plan = plan or SurfacePlan()
    if plan.rounds < 1:
        message = "a surface test runs at least one round"
        raise SurfaceTestRefusedError(message)
    status = writer.status()
    if not status.can_write:
        message = f"cannot run a surface test: {', '.join(status.blockers)}"
        raise SurfaceTestRefusedError(message)
    if sides > 1 and not selects_sides(reader) and flip is None:
        message = (
            f"a {sides}-side test needs the disk turned over between sides, "
            "but nobody is here to do it. Nothing was written"
        )
        raise SurfaceTestRefusedError(message)

    if not confirm(_confirmation_message(sides)):
        message = "the operator declined the surface test"
        raise SurfaceTestRefusedError(message)

    run = _Run(
        writer=writer,
        reader=reader,
        plan=plan,
        sides=sides,
        backup=backup,
        flip=flip,
        progress=progress,
    )
    written = pattern_disk(PATTERNS[1], sides=sides, fill=plan.fill).sides[0]
    stopped, refusal = _run_patterns(run)

    finished, ran = True, False
    if plan.finish is not Finish.LEAVE and stopped is None:
        finished, ran = _finish(run, plan.finish), True

    return SurfaceReport(
        passes=tuple(run.results),
        coverage=written.content_size / LARGEST_FACTORY_SIDE,
        data_bytes=written.content_size,
        finish=plan.finish,
        finish_verified=finished,
        finish_ran=ran,
        stopped=stopped,
        refusal=refusal,
    )
