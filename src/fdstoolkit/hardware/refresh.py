from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from fdstoolkit.core.disk import Disk
from fdstoolkit.drive.captures import Capture
from fdstoolkit.drive.recovery import recover
from fdstoolkit.edit.rebuild import rebuild
from fdstoolkit.hardware.ports import BlockRead, DriveStatus, selects_sides
from fdstoolkit.hardware.session import (
    DumpResult,
    SideDump,
    SideFlipError,
    WriteRefusedError,
    dumped,
    read_disk,
    read_side_with_retries,
)
from fdstoolkit.hardware.writing import WriteReport, write_verified

ONE_SIDE: Final = 1
REWIND: Final = (
    "turn the disk back over so the side A label faces up again before it is written, then confirm"
)
NOT_TURNED_BACK: Final = "the disk was not turned back to side A, so nothing was written"
WRONG_FACE: Final = (
    "side A is not face down: the disk information under the head is not side A's, "
    "so nothing was written"
)


class RefreshRefusedError(WriteRefusedError):
    pass


class RefreshDrive(Protocol):
    @property
    def captures(self) -> tuple[Capture, ...]: ...

    def status(self) -> DriveStatus: ...

    def read_side(self, side: int) -> Iterator[BlockRead]: ...

    def write_side(self, side: int, blocks: Sequence[bytes]) -> None: ...


@dataclass(frozen=True, slots=True)
class RefreshPlan:
    sides: int
    passes: int
    retries: int
    ask: Callable[[str], bool]
    keep: Callable[[Disk], None]
    backup: Callable[[bytes], None] | None
    confirm: Callable[[str], bool] = lambda _: True
    progress: Callable[[str], None] = lambda _: None


@dataclass(frozen=True, slots=True)
class RefreshReport:
    lines: tuple[str, ...]
    image: Disk
    write: WriteReport


def _unsettled(result: DumpResult) -> tuple[str, ...]:
    failed = tuple(
        f"side {side.index} block {block} never read clean and the vote could not rebuild it"
        for side in result.sides
        for block in side.failed_blocks
    )
    missing = tuple(
        f"side {side.index} never reached {side.missing_blocks} declared block(s)"
        for side in result.sides
        if side.missing_blocks
    )
    return (*failed, *missing)


def _settled(drive: RefreshDrive, plan: RefreshPlan) -> tuple[Disk, tuple[str, ...]]:
    reading = read_disk(
        drive,
        sides=plan.sides,
        passes=plan.passes,
        retries=plan.retries,
        flip=plan.ask,
        progress=plan.progress,
    )
    outcome = recover(reading.result, drive.captures)
    unsettled = _unsettled(outcome.result)
    if unsettled:
        message = f"{'; '.join(unsettled)}, so nothing was written"
        raise RefreshRefusedError(message)
    image, _ = rebuild(outcome.result.as_disk())
    return image, (*reading.lines, *(line.strip() for line in outcome.lines))


def _back_on_side_a(drive: RefreshDrive, image: Disk, plan: RefreshPlan) -> None:
    if plan.sides == ONE_SIDE or selects_sides(drive):
        return
    if not plan.ask(REWIND):
        raise SideFlipError(NOT_TURNED_BACK)
    front = dumped(SideDump(index=0, blocks=read_side_with_retries(drive, 0, 0)))
    if front[:1] != [block.payload for block in image.sides[0].blocks[:1]]:
        raise SideFlipError(WRONG_FACE)


def refresh_disk(drive: RefreshDrive, plan: RefreshPlan) -> RefreshReport:
    image, lines = _settled(drive, plan)
    plan.keep(image)
    _back_on_side_a(drive, image, plan)
    report = write_verified(
        drive,
        drive,
        image,
        confirm=plan.confirm,
        backup=plan.backup,
        retries=plan.retries,
        flip=plan.ask,
        progress=plan.progress,
    )
    return RefreshReport(lines=lines, image=image, write=report)
