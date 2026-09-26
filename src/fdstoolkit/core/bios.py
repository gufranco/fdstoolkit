from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.core.diskinfo import VERIFICATION_STRING
from fdstoolkit.edit.files import ExtractedFile, extract_files

APPROVAL_ADDRESS: Final = 0x2800
APPROVAL_LENGTH: Final = 224

BLOCK_EXPECTED: Final = 0x21
CRC_FAILED: Final = 0x27

BIOS_ERRORS: Final[Mapping[int, str]] = {
    0x01: "disk set",
    0x02: "battery",
    0x03: "write protected",
    0x04: "wrong licensee code",
    0x05: "wrong game name or type",
    0x06: "wrong game version",
    0x07: "wrong side number",
    0x08: "wrong disk number",
    0x09: "wrong disk type",
    0x10: "wrong value for unknown field",
    0x20: "approval check failed",
    0x21: "NINTENDO-HVC string mismatch",
    0x22: "block 1 expected",
    0x23: "block 2 expected",
    0x24: "block 3 expected",
    0x25: "block 4 expected",
    0x26: "readback verification failed",
    0x27: "block failed CRC",
    0x28: "file ends prematurely on read",
    0x29: "file ends prematurely on write, disk full",
    0x30: "file ends prematurely during CRC write",
    0x31: "requested count greater than the original file count",
    0x35: "FMC Disk Card Checker block 5 verification failed",
    0x40: "LoadFiles could not load all requested files",
}


class BootVerdict(StrEnum):
    BOOTS = "boots"
    NEEDS_BYPASS = "needs_bypass"
    FAILS = "fails"


@dataclass(frozen=True, slots=True)
class BootFile:
    position: int
    file_id: int
    name: str
    kind: FileKind
    address: int
    size: int


@dataclass(frozen=True, slots=True)
class SideBoot:
    side: int
    verdict: BootVerdict
    error: int | None
    message: str
    boot_files: tuple[BootFile, ...]


@dataclass(frozen=True, slots=True)
class BootReport:
    sides: tuple[SideBoot, ...]


def _describe(code: int) -> str:
    return f"BIOS error {code:02X}, {BIOS_ERRORS[code]}"


def _is_approval(entry: BootFile) -> bool:
    return (
        entry.kind is not FileKind.PROGRAM
        and entry.address <= APPROVAL_ADDRESS
        and entry.address + entry.size >= APPROVAL_ADDRESS + APPROVAL_LENGTH
    )


def _boot_files(files: tuple[ExtractedFile, ...], boot_code: int) -> tuple[BootFile, ...]:
    return tuple(
        BootFile(
            position=entry.position,
            file_id=entry.file_id,
            name=entry.name,
            kind=entry.kind,
            address=entry.address,
            size=entry.size,
        )
        for entry in files
        if entry.file_id <= boot_code and not entry.hidden
    )


def _side_boot(side: Side, index: int, files: tuple[ExtractedFile, ...]) -> SideBoot:
    info = side.disk_info
    if info is None:
        return SideBoot(
            side=index,
            verdict=BootVerdict.FAILS,
            error=0x22,
            message=_describe(0x22),
            boot_files=(),
        )
    if info.verification != VERIFICATION_STRING:
        return SideBoot(
            side=index,
            verdict=BootVerdict.FAILS,
            error=0x21,
            message=_describe(0x21),
            boot_files=(),
        )

    boot = _boot_files(files, info.boot_file)
    if any(_is_approval(entry) for entry in boot):
        return SideBoot(
            side=index,
            verdict=BootVerdict.BOOTS,
            error=None,
            message="boots: a boot file covers the approval data the BIOS compares at $2800",
            boot_files=boot,
        )
    return SideBoot(
        side=index,
        verdict=BootVerdict.NEEDS_BYPASS,
        error=0x20,
        message=(
            f"{_describe(0x20)} when booted cold, unless a boot file enables NMI before the check, "
            "as some unlicensed and Namco titles do, or this is a later disk of a set that the "
            "first disk loads; neither can be decided without running it"
        ),
        boot_files=boot,
    )


def predict_boot(disk: Disk) -> BootReport:
    files = extract_files(disk)
    return BootReport(
        sides=tuple(
            _side_boot(
                side,
                index,
                tuple(entry for entry in files if entry.side == index),
            )
            for index, side in enumerate(disk.sides)
        )
    )
