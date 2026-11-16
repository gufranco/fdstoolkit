from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from fdstoolkit.core.disk import Disk
from fdstoolkit.hardware.ports import DiskReader, DiskWriter, HardwareFaultError
from fdstoolkit.hardware.session import (
    DEFAULT_RETRIES,
    Progress,
    SideFlipError,
    WriteRefusedError,
    quiet,
)
from fdstoolkit.hardware.writing import write_verified

STOPS: Final = (WriteRefusedError, HardwareFaultError, SideFlipError)
FAILED: Final = "failed"


@dataclass(frozen=True, slots=True)
class CopyResult:
    number: int
    verified: bool
    grade: str
    reason: str

    def render(self, count: int) -> str:
        if self.verified:
            return f"copy {self.number} of {count}: verified, grade {self.grade}"
        return f"copy {self.number} of {count}: failed, {self.reason}"


@dataclass(frozen=True, slots=True)
class DuplicateReport:
    count: int
    copies: tuple[CopyResult, ...]
    stopped: bool

    @property
    def verified(self) -> int:
        return sum(1 for copy in self.copies if copy.verified)


def insert_prompt(number: int, count: int) -> str:
    return f"put blank disk {number} of {count} in the drive, then confirm"


def _copy(
    devices: tuple[DiskWriter, DiskReader],
    disk: Disk,
    number: int,
    *,
    ask: Callable[[str], bool],
    retries: int,
    progress: Progress,
) -> CopyResult:
    writer, reader = devices
    try:
        report = write_verified(
            writer,
            reader,
            disk,
            confirm=lambda _: True,
            backup=None,
            retries=retries,
            flip=ask,
            progress=progress,
        )
    except STOPS as error:
        return CopyResult(number=number, verified=False, grade=FAILED, reason=str(error))
    if report.verified:
        return CopyResult(number=number, verified=True, grade=report.grade.value, reason="")
    reason = f"{len(report.mismatched_blocks)} block(s) did not read back as written"
    return CopyResult(number=number, verified=False, grade=report.grade.value, reason=reason)


def duplicate(
    writer: DiskWriter,
    reader: DiskReader,
    disk: Disk,
    *,
    count: int,
    ask: Callable[[str], bool],
    retries: int = DEFAULT_RETRIES,
    progress: Progress = quiet,
) -> DuplicateReport:
    copies: list[CopyResult] = []
    for number in range(1, count + 1):
        if not ask(insert_prompt(number, count)):
            return DuplicateReport(count=count, copies=tuple(copies), stopped=True)
        progress(f"writing copy {number} of {count}")
        copied = _copy((writer, reader), disk, number, ask=ask, retries=retries, progress=progress)
        copies.append(copied)
    return DuplicateReport(count=count, copies=tuple(copies), stopped=False)


def duplicate_lines(report: DuplicateReport) -> tuple[str, ...]:
    lines = [copy.render(report.count) for copy in report.copies]
    if report.stopped:
        made = len(report.copies)
        lines.append(f"the queue stopped after {made} copy(ies): disk {made + 1} was not inserted")
    lines.append(f"{report.verified} of {report.count} copies verified")
    return tuple(lines)
