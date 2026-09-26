from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.build.calibration import LARGEST_FACTORY_SIDE
from fdstoolkit.codecs import fds
from fdstoolkit.core.bitstream import emulated_side_size
from fdstoolkit.core.blocks import Block, BlockKind, declared_blocks
from fdstoolkit.core.disk import Disk, Side, require_readable_sides
from fdstoolkit.hardware.ports import (
    BlockRead,
    DiskReader,
    DiskWriter,
    HardwareFaultError,
    selects_sides,
)

DEFAULT_RETRIES = 3
MAX_RETRIES: Final = 20
MAX_PASSES: Final = 20
MIN_PASSES = 2
EMULATED_CAPACITY = 66560
DISK_INFO_KIND: Final = bytes([BlockKind.DISK_INFO])
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
        if _identified(earlier) and _same_blocks(earlier, dumped[-1]):
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
        return tuple(found)

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


PORTABILITY_NOTE: Final = (
    "verified on this drive only: a drive with misaligned heads writes disks that it reads "
    "back and other drives cannot, so read the disk on a second drive before trusting it"
)
CHANGED_BLOCK: Final = "did not read back as written"
STALE_BLOCK: Final = (
    "is old data past the end of the image, which the write did not reach and a reader "
    "would take for a hidden file"
)
REFUSED_WRITE: Final = (
    "the disk reads back exactly as it was before the write, so it did not take the write. "
    "That is what a drive with an FD3206 controller does when it silently refuses a "
    "full-surface write; check the chip marking, FD3206P rather than FD7201P, before "
    "suspecting the image"
)


@dataclass(frozen=True, slots=True)
class WriteReport:
    verified: bool
    mismatched_blocks: tuple[tuple[int, int], ...]
    dump: DumpResult
    stale_blocks: tuple[tuple[int, int], ...] = ()

    @property
    def grade(self) -> Grade:
        if not self.verified or self.mismatched_blocks:
            return Grade.FAILED
        return self.dump.grade

    @property
    def notes(self) -> tuple[str, ...]:
        if self.verified:
            return (PORTABILITY_NOTE,)
        return ()

    @property
    def findings(self) -> tuple[tuple[int, int, str], ...]:
        stale = set(self.stale_blocks)
        return tuple(
            (side, block, STALE_BLOCK if (side, block) in stale else CHANGED_BLOCK)
            for side, block in self.mismatched_blocks
        )

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(f"side {side}: block {block} {text}" for side, block, text in self.findings)


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


def _missing_from(
    resolved: Sequence[BlockRead], again: Sequence[BlockRead], reads: int
) -> list[BlockRead]:
    have = set(_identities(resolved))
    return [
        BlockRead(
            index=len(resolved) + offset,
            payload=block.payload,
            crc_ok=block.crc_ok,
            attempts=reads,
            stored_crc=block.stored_crc,
        )
        for offset, block in enumerate(
            block
            for identity, block in zip(_identities(again), again, strict=True)
            if identity is not None and identity not in have
        )
    ]


def _read_side_with_retries(reader: DiskReader, side: int, retries: int) -> tuple[BlockRead, ...]:
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
        resolved += _missing_from(resolved, again, reads)
    return tuple(resolved)


Progress = Callable[[str], None]


def _quiet(message: str) -> None:
    del message


def dump(
    reader: DiskReader,
    *,
    sides: int,
    retries: int = DEFAULT_RETRIES,
    flip: Callable[[str], bool] | None = None,
    progress: Progress = _quiet,
) -> DumpResult:
    require_readable_sides(sides)
    _require_readable(reader)
    dumped: list[SideDump] = []
    for side in range(sides):
        if side:
            _ask_for_flip(reader, side, flip)
        progress(f"reading side {side}")
        dumped.append(SideDump(index=side, blocks=_read_side_with_retries(reader, side, retries)))
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
    progress: Progress = _quiet,
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


def _confirmation_message(disk: Disk) -> str:
    return (
        f"overwrite the disk in the drive with {disk.side_count} side(s) of new data, "
        "destroying whatever it holds now"
    )


@dataclass(frozen=True, slots=True)
class SideWrite:
    before: SideDump
    after: SideDump
    mismatched: tuple[int, ...]
    stale: tuple[int, ...] = ()


def write_side_verified(
    writer: DiskWriter,
    reader: DiskReader,
    index: int,
    side: Side,
    *,
    retries: int = DEFAULT_RETRIES,
    progress: Progress = _quiet,
    before_write: Callable[[SideDump], None] = lambda _: None,
) -> SideWrite:
    progress(f"reading side {index} before writing it")
    before = SideDump(index=index, blocks=_read_side_with_retries(reader, index, retries))
    before_write(before)
    progress(f"writing side {index}")
    try:
        writer.write_side(index, [block.payload for block in side.blocks])
    except HardwareFaultError as fault:
        message = f"the write stopped at side {index}: {fault}"
        raise WriteRefusedError(message) from fault
    progress(f"reading side {index} back")
    after = SideDump(index=index, blocks=_read_side_with_retries(reader, index, retries))
    if _same_blocks(after, before) and _payloads(side) != _dumped(before):
        raise WriteNotTakenError(REFUSED_WRITE)
    written = after.blocks
    changed = tuple(
        block_index
        for block_index, block in enumerate(side.blocks)
        if block_index >= len(written) or written[block_index].payload != block.payload
    )
    stale = tuple(range(len(side.blocks), len(written)))
    return SideWrite(before=before, after=after, mismatched=changed + stale, stale=stale)


def refuse_unturned(reader: DiskReader, present: SideDump, previous: SideDump | None) -> None:
    if previous is None or selects_sides(reader) or not _same_blocks(present, previous):
        return
    message = (
        f"side {present.index} reads back exactly what was just written to side "
        f"{previous.index}, so the disk was not turned over. Nothing was written to side "
        f"{present.index}"
    )
    raise SideFlipError(message)


def ask_for_flip(reader: DiskReader, side: int, flip: Callable[[str], bool] | None) -> None:
    _ask_for_flip(reader, side, flip)


def write_verified(
    writer: DiskWriter,
    reader: DiskReader,
    disk: Disk,
    *,
    confirm: Callable[[str], bool],
    backup: Callable[[bytes], None] | None,
    retries: int = DEFAULT_RETRIES,
    flip: Callable[[str], bool] | None = None,
    progress: Progress = _quiet,
) -> WriteReport:
    _require_writable(writer, disk)
    if disk.side_count > 1 and not selects_sides(reader) and flip is None:
        message = (
            f"the image has {disk.side_count} sides and the disk has to be turned over "
            "between them, but nobody is here to do it. Nothing was written"
        )
        raise SideFlipError(message)
    if not confirm(_confirmation_message(disk)):
        message = "the operator declined the write"
        raise WriteRefusedError(message)

    before: list[SideDump] = []
    writes: list[SideWrite] = []

    def keep(present: SideDump) -> None:
        refuse_unturned(reader, present, writes[-1].after if writes else None)
        before.append(present)
        if backup is not None:
            data, _ = fds.encode(DumpResult(sides=tuple(before)).as_disk(), headered=False)
            backup(data)

    for index, side in enumerate(disk.sides):
        if index:
            _ask_for_flip(reader, index, flip)
        writes.append(
            write_side_verified(
                writer, reader, index, side, retries=retries, progress=progress, before_write=keep
            )
        )

    return WriteReport(
        verified=not any(item.mismatched for item in writes),
        mismatched_blocks=tuple(
            (item.after.index, block) for item in writes for block in item.mismatched
        ),
        dump=DumpResult(sides=tuple(item.after for item in writes)),
        stale_blocks=tuple((item.after.index, block) for item in writes for block in item.stale),
    )


def _require_writable(writer: DiskWriter, disk: Disk) -> None:
    status = writer.status()
    if not status.can_write:
        message = f"cannot write: {', '.join(status.blockers)}"
        raise WriteRefusedError(message)
    oversized = [
        index
        for index, side in enumerate(disk.sides)
        if emulated_side_size(side) > EMULATED_CAPACITY
    ]
    if oversized:
        message = (
            f"side {oversized[0]} does not fit a disk: its gapped size is "
            f"{emulated_side_size(disk.sides[oversized[0]])} bytes against a capacity of "
            f"{EMULATED_CAPACITY}"
        )
        raise WriteRefusedError(message)


def refuse_long_sides(disk: Disk) -> None:
    for index, side in enumerate(disk.sides):
        if side.content_size > LARGEST_FACTORY_SIDE:
            message = (
                f"side {index} carries {side.content_size} bytes, more than the "
                f"{LARGEST_FACTORY_SIDE} bytes of the longest factory side measured, so its "
                "last files may run past the end of the track. Nothing was written"
            )
            raise LongSideError(message)


def _same_blocks(first: SideDump, second: SideDump) -> bool:
    return _dumped(first) == _dumped(second)


def _payloads(side: Side) -> list[bytes]:
    return [block.payload for block in side.blocks]


def _dumped(side: SideDump) -> list[bytes]:
    return [block.payload for block in side.blocks]
