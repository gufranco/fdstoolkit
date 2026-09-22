from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.core.blocks import BlockKind, CrcStatus, FileHeader, FileKind
from fdstoolkit.core.disk import Disk, Side

ILLEGAL_OPCODES: Final[frozenset[int]] = frozenset(
    {
        0x02,
        0x03,
        0x04,
        0x07,
        0x0B,
        0x0C,
        0x0F,
        0x12,
        0x13,
        0x14,
        0x17,
        0x1A,
        0x1B,
        0x1C,
        0x1F,
        0x22,
        0x23,
        0x27,
        0x2B,
        0x2F,
        0x32,
        0x33,
        0x34,
        0x37,
        0x3A,
        0x3B,
        0x3C,
        0x3F,
        0x42,
        0x43,
        0x44,
        0x47,
        0x4B,
        0x4F,
        0x52,
        0x53,
        0x54,
        0x57,
        0x5A,
        0x5B,
        0x5C,
        0x5F,
        0x62,
        0x63,
        0x64,
        0x67,
        0x6B,
        0x6F,
        0x72,
        0x73,
        0x74,
        0x77,
        0x7A,
        0x7B,
        0x7C,
        0x7F,
        0x80,
        0x82,
        0x83,
        0x87,
        0x89,
        0x8B,
        0x8F,
        0x92,
        0x93,
        0x97,
        0x9B,
        0x9C,
        0x9E,
        0x9F,
        0xA3,
        0xA7,
        0xAB,
        0xAF,
        0xB2,
        0xB3,
        0xB7,
        0xBB,
        0xBF,
        0xC2,
        0xC3,
        0xC7,
        0xCB,
        0xCF,
        0xD2,
        0xD3,
        0xD4,
        0xD7,
        0xDA,
        0xDB,
        0xDC,
        0xDF,
        0xE2,
        0xE3,
        0xE7,
        0xEB,
        0xEF,
        0xF2,
        0xF3,
        0xF4,
        0xF7,
        0xFA,
        0xFB,
        0xFC,
        0xFF,
    }
)

ILLEGAL_SHARE: Final = 0.25
MIN_CODE_BYTES: Final = 64


class Suspicion(StrEnum):
    IMPLAUSIBLE_CODE = "implausible code"
    SIZE_MISMATCH = "size mismatch"
    REGENERATED_CRCS = "regenerated crcs"


@dataclass(frozen=True, slots=True)
class CodeReport:
    examined: int
    illegal: int

    @property
    def share(self) -> float:
        if not self.examined:
            return 0.0
        return self.illegal / self.examined

    @property
    def plausible(self) -> bool:
        if self.examined < MIN_CODE_BYTES:
            return True
        return self.share < ILLEGAL_SHARE


@dataclass(frozen=True, slots=True)
class Finding:
    kind: Suspicion
    side: int
    detail: str


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    suspicions: tuple[Finding, ...]

    @property
    def sound(self) -> bool:
        return not self.suspicions


def code_sanity(body: bytes) -> CodeReport:
    illegal = sum(1 for byte in body if byte in ILLEGAL_OPCODES)
    return CodeReport(examined=len(body), illegal=illegal)


def _file_finding(header: FileHeader, body: bytes, side: int) -> Finding | None:
    if len(body) != header.size:
        return Finding(
            kind=Suspicion.SIZE_MISMATCH,
            side=side,
            detail=f"{header.name} declares {header.size} bytes and carries {len(body)}",
        )
    if header.kind is not FileKind.PROGRAM:
        return None
    report = code_sanity(body)
    if report.plausible:
        return None
    return Finding(
        kind=Suspicion.IMPLAUSIBLE_CODE,
        side=side,
        detail=f"{header.name} is {report.share:.0%} undocumented opcodes",
    )


def _side_findings(side: Side, index: int, *, expect_original_crcs: bool) -> list[Finding]:
    findings: list[Finding] = []
    pending: FileHeader | None = None
    stored = recomputed = 0

    for block in side.blocks:
        if block.stored_crc is not None:
            stored += 1
            recomputed += block.crc_status is CrcStatus.VALID

        if block.kind is BlockKind.FILE_HEADER:
            pending = FileHeader.parse(block.payload)
            continue
        if block.kind is not BlockKind.FILE_DATA or pending is None:
            continue

        found = _file_finding(pending, block.payload[1:], index)
        if found is not None:
            findings.append(found)
        pending = None

    if expect_original_crcs and stored and stored == recomputed:
        findings.append(
            Finding(
                kind=Suspicion.REGENERATED_CRCS,
                side=index,
                detail=f"all {stored} stored CRCs recompute exactly",
            )
        )
    return findings


def inspect_disk(disk: Disk, *, expect_original_crcs: bool = False) -> IntegrityReport:
    findings = [
        finding
        for index, side in enumerate(disk.sides)
        for finding in _side_findings(side, index, expect_original_crcs=expect_original_crcs)
    ]
    return IntegrityReport(suspicions=tuple(findings))
