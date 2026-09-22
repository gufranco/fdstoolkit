from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from fdstk.core.blocks import (
    DISK_INFO_SIZE,
    FILE_AMOUNT_SIZE,
    FILE_HEADER_SIZE,
    Block,
    BlockKind,
    CrcStatus,
    FileHeader,
)
from fdstk.core.crc import CRC_SIZE, decode_crc
from fdstk.core.diagnostics import CODES, Diagnostic, Severity
from fdstk.core.disk import Side
from fdstk.core.diskinfo import VERIFICATION_STRING, DiskInfo

NEXT_KIND: Final[dict[BlockKind, BlockKind]] = {
    BlockKind.DISK_INFO: BlockKind.FILE_AMOUNT,
    BlockKind.FILE_AMOUNT: BlockKind.FILE_HEADER,
    BlockKind.FILE_HEADER: BlockKind.FILE_DATA,
    BlockKind.FILE_DATA: BlockKind.FILE_HEADER,
}


@dataclass(slots=True)
class _Walk:
    blocks: list[Block]
    findings: list[Diagnostic]
    position: int
    expected: BlockKind
    pending_size: int


def _diagnostic(
    code: str,
    severity: Severity,
    side_index: int,
    offset: int | None = None,
    detail: dict[str, object] | None = None,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        severity=severity,
        message=CODES[code],
        side=side_index,
        offset=offset,
        detail=detail or {},
    )


def _block_length(kind: BlockKind, pending_size: int) -> int:
    if kind is BlockKind.DISK_INFO:
        return DISK_INFO_SIZE
    if kind is BlockKind.FILE_AMOUNT:
        return FILE_AMOUNT_SIZE
    if kind is BlockKind.FILE_HEADER:
        return FILE_HEADER_SIZE
    return 1 + pending_size


def _check_crc(block: Block, side_index: int, offset: int) -> Diagnostic | None:
    if block.crc_status is CrcStatus.MISMATCH:
        return _diagnostic(
            "FDS002",
            Severity.ERROR,
            side_index,
            offset,
            {"stored": block.stored_crc, "computed": block.computed_crc},
        )
    if block.crc_status is CrcStatus.NULL:
        return _diagnostic("FDS003", Severity.INFO, side_index, offset)
    return None


def _walk(data: bytes, *, has_crc: bool, side_index: int) -> _Walk:
    walk = _Walk(blocks=[], findings=[], position=0, expected=BlockKind.DISK_INFO, pending_size=0)
    while walk.position < len(data):
        offset = walk.position
        code = data[offset]
        if code != int(walk.expected):
            if walk.blocks and code != 0:
                walk.findings.append(
                    _diagnostic(
                        "FDS005",
                        Severity.WARNING,
                        side_index,
                        offset,
                        {"found": code, "expected": int(walk.expected)},
                    )
                )
            break
        length = _block_length(walk.expected, walk.pending_size)
        payload = data[offset : offset + length]
        if len(payload) != length:
            walk.findings.append(
                _diagnostic(
                    "FDS004",
                    Severity.ERROR,
                    side_index,
                    offset,
                    {"expected": length, "available": len(payload)},
                )
            )
            break
        stored: int | None = None
        if has_crc:
            crc_bytes = data[offset + length : offset + length + CRC_SIZE]
            if len(crc_bytes) != CRC_SIZE:
                walk.findings.append(
                    _diagnostic(
                        "FDS004",
                        Severity.ERROR,
                        side_index,
                        offset,
                        {"expected": length + CRC_SIZE, "available": len(payload) + len(crc_bytes)},
                    )
                )
                break
            stored = decode_crc(crc_bytes)
        block = Block(kind=walk.expected, payload=payload, stored_crc=stored)
        finding = _check_crc(block, side_index, offset)
        if finding is not None:
            walk.findings.append(finding)
        if walk.expected is BlockKind.FILE_HEADER:
            walk.pending_size = FileHeader.parse(payload).size
        walk.blocks.append(block)
        walk.position = offset + length + (CRC_SIZE if has_crc else 0)
        walk.expected = NEXT_KIND[walk.expected]
    return walk


def parse_side(
    data: bytes,
    *,
    has_crc: bool,
    side_index: int = 0,
    capacity: int | None = None,
) -> tuple[Side, tuple[Diagnostic, ...]]:
    walk = _walk(data, has_crc=has_crc, side_index=side_index)
    side = Side(
        blocks=tuple(walk.blocks),
        tail=data[walk.position :].rstrip(b"\0"),
        capacity=len(data) if capacity is None else capacity,
    )
    findings = list(walk.findings)

    if not side.is_formatted:
        findings.insert(0, _diagnostic("FDS001", Severity.WARNING, side_index, 0))
    else:
        info = DiskInfo.parse(side.blocks[0].payload)
        if info.verification != VERIFICATION_STRING:
            findings.append(
                _diagnostic(
                    "FDS008",
                    Severity.ERROR,
                    side_index,
                    0x01,
                    {"found": info.verification.decode("ascii", errors="replace")},
                )
            )

    declared = side.declared_file_count
    if declared is not None and side.file_count > declared:
        findings.append(
            _diagnostic(
                "FDS006",
                Severity.INFO,
                side_index,
                None,
                {"declared": declared, "found": side.file_count},
            )
        )
    if declared is not None and side.file_count < declared:
        findings.append(
            _diagnostic(
                "FDS009",
                Severity.WARNING,
                side_index,
                None,
                {"declared": declared, "found": side.file_count},
            )
        )

    if side.has_data_after_last_block:
        findings.append(
            _diagnostic(
                "FDS007",
                Severity.WARNING,
                side_index,
                walk.position,
                {"bytes": len(side.tail.strip(b"\0"))},
            )
        )

    return side, tuple(findings)
