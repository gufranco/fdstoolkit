from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final

from fdstoolkit.core.blocks import (
    DISK_INFO_SIZE,
    FILE_AMOUNT_SIZE,
    FILE_HEADER_SIZE,
    TEST_BLOCK_CODE,
    TEST_PATTERN,
    Block,
    BlockKind,
    CrcStatus,
    FileHeader,
)
from fdstoolkit.core.crc import CRC_SIZE, block_crc, crc_boundary, decode_crc
from fdstoolkit.core.diagnostics import CODES, Diagnostic, Severity
from fdstoolkit.core.disk import Side
from fdstoolkit.core.diskinfo import VERIFICATION_STRING, DiskInfo

NEXT_KIND: Final[dict[BlockKind, BlockKind]] = {
    BlockKind.DISK_INFO: BlockKind.FILE_AMOUNT,
    BlockKind.FILE_AMOUNT: BlockKind.FILE_HEADER,
    BlockKind.FILE_HEADER: BlockKind.FILE_DATA,
    BlockKind.FILE_DATA: BlockKind.FILE_HEADER,
}
RESCAN_SIDES: Final = 2
PATTERN_REPEATS: Final = 4


@dataclass(frozen=True, slots=True)
class _Walk:
    blocks: tuple[Block, ...]
    findings: tuple[Diagnostic, ...]
    position: int
    expected: BlockKind
    pending_size: int
    rescan_budget: int
    done: bool = False


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


def _ends_a_block(data: bytes, end: int) -> bool:
    rest = data[end:]
    return not rest.strip(b"\0") or rest[0] == BlockKind.FILE_HEADER


def _other_length(data: bytes, offset: int, declared: int) -> int | None:
    block = data[offset:]

    def ends(size: int) -> bool:
        return size != declared and _ends_a_block(block, size + CRC_SIZE)

    return crc_boundary(block, range(2, len(block) - CRC_SIZE + 1), ends)


def _true_length(
    walk: _Walk, data: bytes, offset: int, length: int, side_index: int
) -> tuple[_Walk, int]:
    payload = data[offset : offset + length]
    stored = decode_crc(data[offset + length : offset + length + CRC_SIZE])
    if walk.expected is not BlockKind.FILE_DATA or stored == block_crc(payload):
        return walk, length
    remaining = len(data) - offset
    if remaining > walk.rescan_budget:
        return walk, length
    spent = replace(walk, rescan_budget=walk.rescan_budget - remaining)
    found = _other_length(data, offset, length)
    if found is None:
        return spent, length
    finding = _diagnostic(
        "FDS016" if found > length else "FDS012",
        Severity.WARNING,
        side_index,
        offset,
        {"declared": length - 1, "actual": found - 1},
    )
    return replace(spent, findings=(*spent.findings, finding)), found


def _stop(walk: _Walk, finding: Diagnostic | None) -> _Walk:
    found = () if finding is None else (finding,)
    return replace(walk, findings=(*walk.findings, *found), done=True)


def _truncated(side_index: int, offset: int, expected: int, available: int) -> Diagnostic:
    detail: dict[str, object] = {"expected": expected, "available": available}
    return _diagnostic("FDS004", Severity.ERROR, side_index, offset, detail)


def _unexpected(walk: _Walk, code: int, side_index: int, offset: int) -> Diagnostic | None:
    if not walk.blocks or code in {0, TEST_BLOCK_CODE}:
        return None
    detail: dict[str, object] = {"found": code, "expected": int(walk.expected)}
    return _diagnostic("FDS005", Severity.WARNING, side_index, offset, detail)


def _accepted(walk: _Walk, block: Block, side_index: int, offset: int, end: int) -> _Walk:
    finding = _check_crc(block, side_index, offset)
    header = block.kind is BlockKind.FILE_HEADER
    return replace(
        walk,
        blocks=(*walk.blocks, block),
        findings=(*walk.findings, *(() if finding is None else (finding,))),
        position=end,
        expected=NEXT_KIND[walk.expected],
        pending_size=FileHeader.parse(block.payload).size if header else walk.pending_size,
    )


def _checked(walk: _Walk, data: bytes, side_index: int, offset: int, length: int) -> _Walk:
    crc_bytes = data[offset + length : offset + length + CRC_SIZE]
    if len(crc_bytes) != CRC_SIZE:
        available = length + len(crc_bytes)
        return _stop(walk, _truncated(side_index, offset, length + CRC_SIZE, available))
    measured, true_length = _true_length(walk, data, offset, length, side_index)
    end = offset + true_length
    stored = decode_crc(data[end : end + CRC_SIZE])
    block = Block(kind=walk.expected, payload=data[offset:end], stored_crc=stored)
    return _accepted(measured, block, side_index, offset, end + CRC_SIZE)


def _step(walk: _Walk, data: bytes, *, has_crc: bool, side_index: int) -> _Walk:
    offset = walk.position
    code = data[offset]
    if code != int(walk.expected):
        return _stop(walk, _unexpected(walk, code, side_index, offset))
    length = _block_length(walk.expected, walk.pending_size)
    payload = data[offset : offset + length]
    if len(payload) != length:
        return _stop(walk, _truncated(side_index, offset, length, len(payload)))
    if has_crc:
        return _checked(walk, data, side_index, offset, length)
    block = Block(kind=walk.expected, payload=payload)
    return _accepted(walk, block, side_index, offset, offset + length)


def _walk(data: bytes, *, has_crc: bool, side_index: int) -> _Walk:
    walk = _Walk(
        blocks=(),
        findings=(),
        position=0,
        expected=BlockKind.DISK_INFO,
        pending_size=0,
        rescan_budget=RESCAN_SIDES * len(data),
    )
    while not walk.done and walk.position < len(data):
        walk = _step(walk, data, has_crc=has_crc, side_index=side_index)
    return walk


def _format_findings(
    side: Side, side_index: int, walked: tuple[Diagnostic, ...]
) -> tuple[Diagnostic, ...]:
    if not side.is_formatted:
        return (_diagnostic("FDS001", Severity.WARNING, side_index, 0), *walked)
    info = DiskInfo.parse(side.blocks[0].payload)
    if info.verification == VERIFICATION_STRING:
        return walked
    found = info.verification.decode("ascii", errors="replace")
    detail: dict[str, object] = {"found": found}
    return (*walked, _diagnostic("FDS008", Severity.ERROR, side_index, 0x01, detail))


def _count_findings(side: Side, side_index: int) -> tuple[Diagnostic, ...]:
    declared = side.declared_file_count
    if declared is None or side.file_count == declared:
        return ()
    detail: dict[str, object] = {"declared": declared, "found": side.file_count}
    if side.file_count > declared:
        return (_diagnostic("FDS006", Severity.INFO, side_index, None, detail),)
    return (_diagnostic("FDS009", Severity.WARNING, side_index, None, detail),)


def parse_side(
    data: bytes,
    *,
    has_crc: bool,
    side_index: int = 0,
    capacity: int | None = None,
) -> tuple[Side, tuple[Diagnostic, ...]]:
    walk = _walk(data, has_crc=has_crc, side_index=side_index)
    side = Side(
        blocks=walk.blocks,
        tail=data[walk.position :].rstrip(b"\0"),
        capacity=len(data) if capacity is None else capacity,
    )
    trailing = (
        (_trailing(side, walk.position, side_index),) if side.has_data_after_last_block else ()
    )
    findings = (
        *_format_findings(side, side_index, walk.findings),
        *_count_findings(side, side_index),
        *trailing,
    )
    return side, findings


def _test_pattern(data: bytes) -> bool:
    sample = data[: len(TEST_PATTERN) * PATTERN_REPEATS]
    return bool(sample) and sample == (TEST_PATTERN * PATTERN_REPEATS)[: len(sample)]


def _trailing(side: Side, position: int, side_index: int) -> Diagnostic:
    if side.tail[:1] == bytes([TEST_BLOCK_CODE]):
        detail: dict[str, object] = {"pattern": _test_pattern(side.tail[1:])}
        return _diagnostic("FDS020", Severity.INFO, side_index, position, detail)
    return _diagnostic(
        "FDS007",
        Severity.WARNING,
        side_index,
        position,
        {"bytes": len(side.tail.strip(b"\0"))},
    )
