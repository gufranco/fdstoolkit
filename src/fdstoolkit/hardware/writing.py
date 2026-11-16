from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from fdstoolkit.build.calibration import LARGEST_FACTORY_SIDE
from fdstoolkit.codecs import fds
from fdstoolkit.core.bitstream import EMULATION_BUFFER, emulated_side_size
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.hardware.ports import (
    DiskReader,
    DiskWriter,
    HardwareFaultError,
    selects_sides,
)
from fdstoolkit.hardware.session import (
    DEFAULT_RETRIES,
    DumpResult,
    Grade,
    HalfWriteError,
    LongSideError,
    Progress,
    SideDump,
    SideFlipError,
    WriteNotTakenError,
    WriteRefusedError,
    ask_for_flip,
    dumped,
    quiet,
    read_side_with_retries,
    same_blocks,
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
    "suspecting the image. A side whose write-protect tab is broken off may be refused too, "
    "though whether the drive enforces the tab for an FDSStick is not documented. Some drives "
    "also carry a lockout circuit that blocks the write gate, with no error, when it rises "
    "before the drive reports ready or stays up past about a second"
)


HALF_WRITE: Final = (
    "the disk took everything but its disk information block, which still reads as it was "
    "before the write. That is a drive whose power board is not modified for writing: only "
    "an FMD-POWER-01 board, or a later one modified for it, rewrites the Nintendo header. "
    "The disk is now half written; dump it before using it"
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

    @property
    def changed(self) -> tuple[int, ...]:
        return tuple(block for block in self.mismatched if block not in self.stale)


def _judged(side: Side, before: SideDump, after: SideDump) -> SideWrite:
    if same_blocks(after, before) and _payloads(side) != dumped(before):
        raise WriteNotTakenError(REFUSED_WRITE)
    if _kept_header(side, before, after):
        raise HalfWriteError(HALF_WRITE)
    written = after.blocks
    changed = tuple(
        block_index
        for block_index, block in enumerate(side.blocks)
        if block_index >= len(written)
        or written[block_index].payload != block.payload
        or not written[block_index].crc_ok
    )
    stale = tuple(range(len(side.blocks), len(written)))
    return SideWrite(before=before, after=after, mismatched=changed + stale, stale=stale)


def _write(writer: DiskWriter, index: int, side: Side) -> None:
    try:
        writer.write_side(index, [block.payload for block in side.blocks])
    except HardwareFaultError as fault:
        message = f"the write stopped at side {index}: {fault}"
        raise WriteRefusedError(message) from fault


def write_side_verified(
    writer: DiskWriter,
    reader: DiskReader,
    index: int,
    side: Side,
    *,
    retries: int = DEFAULT_RETRIES,
    progress: Progress = quiet,
    before_write: Callable[[SideDump], None] = lambda _: None,
) -> SideWrite:
    progress(f"reading side {index} before writing it")
    before = SideDump(index=index, blocks=read_side_with_retries(reader, index, retries))
    before_write(before)
    progress(f"writing side {index}")
    _write(writer, index, side)
    progress(f"reading side {index} back")
    after = SideDump(index=index, blocks=read_side_with_retries(reader, index, retries))
    return _judged(side, before, after)


def refuse_unturned(reader: DiskReader, present: SideDump, previous: SideDump | None) -> None:
    if previous is None or selects_sides(reader) or not same_blocks(present, previous):
        return
    message = (
        f"side {present.index} reads back exactly what was just written to side "
        f"{previous.index}, so the disk was not turned over. Nothing was written to side "
        f"{present.index}"
    )
    raise SideFlipError(message)


def _refuse_unattended(reader: DiskReader, disk: Disk, flip: Callable[[str], bool] | None) -> None:
    if disk.side_count > 1 and not selects_sides(reader) and flip is None:
        message = (
            f"the image has {disk.side_count} sides and the disk has to be turned over "
            "between them, but nobody is here to do it. Nothing was written"
        )
        raise SideFlipError(message)


@dataclass(frozen=True, slots=True)
class _Plan:
    retries: int
    backup: Callable[[bytes], None] | None
    flip: Callable[[str], bool] | None
    progress: Progress


def _write_sides(
    writer: DiskWriter, reader: DiskReader, disk: Disk, plan: _Plan
) -> tuple[SideWrite, ...]:
    before: list[SideDump] = []
    writes: list[SideWrite] = []

    def keep(present: SideDump) -> None:
        refuse_unturned(reader, present, writes[-1].after if writes else None)
        if present.side_note:
            plan.progress(present.side_note)
        before.append(present)
        if plan.backup is not None:
            data, _ = fds.encode(DumpResult(sides=tuple(before)).as_disk(), headered=False)
            plan.backup(data)

    for index, side in enumerate(disk.sides):
        if index:
            ask_for_flip(reader, index, plan.flip)
        writes.append(
            write_side_verified(
                writer,
                reader,
                index,
                side,
                retries=plan.retries,
                progress=plan.progress,
                before_write=keep,
            )
        )
    return tuple(writes)


def _report(writes: tuple[SideWrite, ...]) -> WriteReport:
    return WriteReport(
        verified=not any(item.mismatched for item in writes),
        mismatched_blocks=tuple(
            (item.after.index, block) for item in writes for block in item.mismatched
        ),
        dump=DumpResult(sides=tuple(item.after for item in writes)),
        stale_blocks=tuple((item.after.index, block) for item in writes for block in item.stale),
    )


def write_verified(
    writer: DiskWriter,
    reader: DiskReader,
    disk: Disk,
    *,
    confirm: Callable[[str], bool],
    backup: Callable[[bytes], None] | None,
    retries: int = DEFAULT_RETRIES,
    flip: Callable[[str], bool] | None = None,
    progress: Progress = quiet,
) -> WriteReport:
    _require_writable(writer, disk)
    _refuse_unattended(reader, disk, flip)
    if not confirm(_confirmation_message(disk)):
        message = "the operator declined the write"
        raise WriteRefusedError(message)
    plan = _Plan(retries=retries, backup=backup, flip=flip, progress=progress)
    return _report(_write_sides(writer, reader, disk, plan))


def _require_writable(writer: DiskWriter, disk: Disk) -> None:
    status = writer.status()
    if not status.can_write:
        message = f"cannot write: {', '.join(status.blockers)}"
        raise WriteRefusedError(message)
    oversized = [
        index
        for index, side in enumerate(disk.sides)
        if emulated_side_size(side) > EMULATION_BUFFER
    ]
    if oversized:
        message = (
            f"side {oversized[0]} does not fit a disk: its gapped size is "
            f"{emulated_side_size(disk.sides[oversized[0]])} bytes against a capacity of "
            f"{EMULATION_BUFFER}"
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


def _kept_header(side: Side, before: SideDump, after: SideDump) -> bool:
    wanted = _payloads(side)
    was, now = dumped(before), dumped(after)
    if not (wanted and was and now) or wanted[0] == was[0] or now[0] != was[0]:
        return False
    return now[1:] == wanted[1 : len(now)]


def _payloads(side: Side) -> list[bytes]:
    return [block.payload for block in side.blocks]
