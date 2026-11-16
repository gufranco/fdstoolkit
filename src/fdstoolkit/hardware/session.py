from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

from fdstoolkit.core.bios import BIOS_ERRORS, BLOCK_EXPECTED, CRC_FAILED
from fdstoolkit.core.blocks import Block, BlockKind, declared_blocks, expected_kind
from fdstoolkit.core.disk import SIDE_SIZE, SIDES_PER_DISK, Disk, Side, require_readable_sides
from fdstoolkit.core.diskinfo import FIELDS_BY_NAME
from fdstoolkit.hardware.ports import (
    BlockRead,
    DiskReader,
    selects_sides,
)

DEFAULT_RETRIES = 3


MAX_RETRIES: Final = 20


MAX_PASSES: Final = 20


MIN_PASSES = 2


DISK_INFO_KIND: Final = bytes([BlockKind.DISK_INFO])


SIDE_OFFSET: Final = FIELDS_BY_NAME["side"].offset


SIDE_NAMES: Final = ("A", "B")


FILE_AMOUNT_KIND: Final = bytes([BlockKind.FILE_AMOUNT])


class Grade(StrEnum):
    CLEAN = "clean"
    MARGINAL = "marginal"
    UNSTABLE = "unstable"
    FAILED = "failed"


SEVERITY: Final = (Grade.FAILED, Grade.UNSTABLE, Grade.MARGINAL, Grade.CLEAN)


def worst_grade(*grades: Grade) -> Grade:
    return min(grades, key=SEVERITY.index, default=Grade.CLEAN)


class WriteRefusedError(Exception):
    pass


class WriteNotTakenError(WriteRefusedError):
    pass


class LongSideError(WriteRefusedError):
    pass


class HalfWriteError(WriteRefusedError):
    pass


class SideFlipError(Exception):
    pass


def _flip_message(side: int) -> str:
    face = "B" if side % 2 else "A"
    return (
        f"turn the disk over so the side {face} label faces up, then confirm. "
        f"The head sits under the disk and reads side {face} from the face turned down, "
        "so this drive cannot select a side on its own"
    )


def _rewind_message() -> str:
    return (
        "turn the disk back over so the side A label faces up again for the next pass, then confirm"
    )


def _ask_for_flip(reader: DiskReader, side: int, flip: Callable[[str], bool] | None) -> None:
    if selects_sides(reader):
        return
    if flip is None:
        message = (
            f"side {side} needs the disk turned over and no one is present to do it. "
            "Dump one side at a time, or pass a confirmation callback"
        )
        raise SideFlipError(message)
    if not flip(_flip_message(side)):
        message = f"the operator declined to turn the disk over for side {side}"
        raise SideFlipError(message)


def _identified(side: SideDump) -> bool:
    blocks = side.blocks
    return bool(blocks) and blocks[0].crc_ok and blocks[0].payload[:1] == DISK_INFO_KIND


def _reject_unflipped(dumped: Sequence[SideDump], side: int) -> None:
    if not _identified(dumped[-1]):
        return
    for earlier in dumped[:-1]:
        if _identified(earlier) and same_blocks(earlier, dumped[-1]):
            message = (
                f"side {side} read the same bytes as side {earlier.index}, "
                "so the disk was not turned over. Nothing was written"
            )
            raise SideFlipError(message)


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
    def missing_blocks(self) -> int:
        return max(_declared(self.blocks) - len(self.blocks), 0)

    @property
    def lines(self) -> tuple[str, ...]:
        found: list[str] = []
        if self.marginal_blocks:
            found.append(
                f"side {self.index}: {len(self.marginal_blocks)} block(s) only read clean on "
                "a re-read, so this disk is wearing"
            )
        if self.failed_blocks:
            found.append(
                f"side {self.index}: {len(self.failed_blocks)} block(s) never read clean, "
                f"blocks {', '.join(str(index) for index in self.failed_blocks)}"
            )
        if self.missing_blocks:
            found.append(
                f"side {self.index}: {self.missing_blocks} block(s) the side declares were never "
                f"found, after block {len(self.blocks) - 1}"
            )
        note = self.side_note
        if note:
            found.append(note)
        error = self.console_error
        if error is not None:
            found.append(
                f"side {self.index}: a console stops this side with error {error:02X}, "
                f"{BIOS_ERRORS[error]}"
            )
        return tuple(found)

    @property
    def console_error(self) -> int | None:
        if not self.blocks:
            return BLOCK_EXPECTED + BlockKind.DISK_INFO
        declared = _declared(self.blocks)
        if any(index < declared or not declared for index in self.failed_blocks):
            return CRC_FAILED
        if self.missing_blocks:
            return BLOCK_EXPECTED + expected_kind(len(self.blocks))
        return None

    @property
    def side_note(self) -> str:
        if not _identified(self):
            return ""
        named = self.blocks[0].payload[SIDE_OFFSET] % SIDES_PER_DISK
        if named == self.index % SIDES_PER_DISK:
            return ""
        face = SIDE_NAMES[named]
        return (
            f"side {self.index}: its disk information says side {face}, so the disk may be in "
            f"the drive with side {face}'s label up"
        )

    @property
    def grade(self) -> Grade:
        if self.failed_blocks or self.missing_blocks or not self.blocks:
            return Grade.FAILED
        if self.marginal_blocks:
            return Grade.MARGINAL
        return Grade.CLEAN

    def as_side(self, capacity: int) -> Side:
        return Side(
            blocks=tuple(
                Block(
                    kind=BlockKind(block.payload[0]),
                    payload=block.payload,
                    stored_crc=block.stored_crc,
                )
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

    def as_disk(self, capacity: int = SIDE_SIZE) -> Disk:
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


def _require_readable(reader: DiskReader) -> None:
    status = reader.status()
    if not status.can_read:
        message = f"cannot read: {', '.join(status.blockers)}"
        raise WriteRefusedError(message)


Identity = tuple[int, int]


NO_FILE: Final = -1


def _identities(blocks: Sequence[BlockRead]) -> tuple[Identity | None, ...]:
    number = NO_FILE
    found: list[Identity | None] = []
    for block in blocks:
        if not block.payload:
            found.append(None)
            continue
        kind = block.payload[0]
        if kind == BlockKind.FILE_HEADER and len(block.payload) > 1:
            number = block.payload[1]
        found.append(
            (kind, number if kind in {BlockKind.FILE_HEADER, BlockKind.FILE_DATA} else NO_FILE)
        )
    return tuple(found)


def _declared(blocks: Sequence[BlockRead]) -> int:
    for block in blocks:
        if block.crc_ok and block.payload[:1] == FILE_AMOUNT_KIND:
            return declared_blocks(block.payload)
    return 0


def _unfinished(blocks: Sequence[BlockRead]) -> bool:
    return any(not block.crc_ok for block in blocks) or len(blocks) < _declared(blocks)


def _keys(blocks: Sequence[BlockRead]) -> list[tuple[Identity | None, int]]:
    seen: Counter[Identity | None] = Counter()
    keys: list[tuple[Identity | None, int]] = []
    for identity in _identities(blocks):
        keys.append((identity, seen[identity]))
        seen[identity] += 1
    return keys


def _merged(
    resolved: Sequence[BlockRead], again: Sequence[BlockRead], reads: int
) -> list[BlockRead]:
    if len(resolved) >= _declared(resolved) or len(again) <= len(resolved):
        return list(resolved)
    first = {block.payload: block.attempts for block in resolved if block.crc_ok}
    return [replace(block, attempts=first.get(block.payload, reads)) for block in again]


def read_side_with_retries(reader: DiskReader, side: int, retries: int) -> tuple[BlockRead, ...]:
    resolved = list(reader.read_side(side))
    reads = 1
    while reads <= retries and _unfinished(resolved):
        reads += 1
        again = list(reader.read_side(side))
        wanted = _identities(resolved)
        clean = {
            identity: block
            for identity, block in zip(_identities(again), again, strict=True)
            if identity is not None and block.crc_ok
        }
        for position, block in enumerate(resolved):
            if block.crc_ok:
                continue
            identity = wanted[position]
            match = clean.get(identity) if identity is not None else None
            found = match or block
            resolved[position] = BlockRead(
                index=position,
                payload=found.payload,
                crc_ok=match is not None,
                attempts=reads,
                stored_crc=found.stored_crc,
            )
        resolved = _merged(resolved, again, reads)
    return tuple(resolved)


Progress = Callable[[str], None]


def quiet(message: str) -> None:
    del message


def dump(
    reader: DiskReader,
    *,
    sides: int,
    retries: int = DEFAULT_RETRIES,
    flip: Callable[[str], bool] | None = None,
    progress: Progress = quiet,
) -> DumpResult:
    require_readable_sides(sides)
    _require_readable(reader)
    dumped: list[SideDump] = []
    for side in range(sides):
        if side:
            _ask_for_flip(reader, side, flip)
        progress(f"reading side {side}")
        dumped.append(SideDump(index=side, blocks=read_side_with_retries(reader, side, retries)))
        if side and not selects_sides(reader):
            _reject_unflipped(dumped, side)
    return DumpResult(sides=tuple(dumped))


def dump_repeated(
    reader: DiskReader,
    *,
    sides: int,
    passes: int = MIN_PASSES,
    retries: int = DEFAULT_RETRIES,
    flip: Callable[[str], bool] | None = None,
    progress: Progress = quiet,
) -> StabilityReport:
    if passes < MIN_PASSES:
        message = f"a stability check needs at least two passes, got {passes}"
        raise ValueError(message)

    collected: list[DumpResult] = []
    for attempt in range(passes):
        rewind = attempt and sides > 1 and not selects_sides(reader)
        if rewind and (flip is None or not flip(_rewind_message())):
            message = "the disk was not returned to side A, so the passes cannot be compared"
            raise SideFlipError(message)
        collected.append(dump(reader, sides=sides, retries=retries, flip=flip, progress=progress))
    results = tuple(collected)
    unstable = tuple(
        (side_index, block.index)
        for side_index, side in enumerate(results[0].sides)
        for block in _moving(side_index, side, results)
    )
    return StabilityReport(passes=results, unstable_blocks=unstable)


def _moving(side_index: int, side: SideDump, results: Sequence[DumpResult]) -> list[BlockRead]:
    maps = [
        dict(
            zip(_keys(other.sides[side_index].blocks), other.sides[side_index].blocks, strict=True)
        )
        for other in results
    ]
    return [
        block
        for key, block in zip(_keys(side.blocks), side.blocks, strict=True)
        if len({found[key].payload for found in maps if key in found}) > 1
    ]


@dataclass(frozen=True, slots=True)
class Reading:
    result: DumpResult
    grade: Grade
    unstable_blocks: tuple[tuple[int, int], ...] = ()

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(
            f"side {side}: block {block} differs between passes"
            for side, block in self.unstable_blocks
        )

    def settled(self, recovered: DumpResult, *, changed: bool) -> Grade:
        if not changed:
            return self.grade
        return worst_grade(recovered.grade, Grade.UNSTABLE if self.unstable_blocks else Grade.CLEAN)


def read_disk(
    reader: DiskReader,
    *,
    sides: int,
    passes: int,
    retries: int = DEFAULT_RETRIES,
    flip: Callable[[str], bool] | None = None,
    progress: Progress = quiet,
) -> Reading:
    if passes == 1:
        result = dump(reader, sides=sides, retries=retries, flip=flip, progress=progress)
        return Reading(result=result, grade=result.grade)
    report = dump_repeated(
        reader, sides=sides, passes=passes, retries=retries, flip=flip, progress=progress
    )
    return Reading(
        result=report.passes[0], grade=report.grade, unstable_blocks=report.unstable_blocks
    )


def ask_for_flip(reader: DiskReader, side: int, flip: Callable[[str], bool] | None) -> None:
    _ask_for_flip(reader, side, flip)


def same_blocks(first: SideDump, second: SideDump) -> bool:
    return dumped(first) == dumped(second)


def dumped(side: SideDump) -> list[bytes]:
    return [block.payload for block in side.blocks]
