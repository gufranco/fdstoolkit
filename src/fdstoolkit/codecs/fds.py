from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from fdstoolkit.core.blocks import BlockKind, FileHeader
from fdstoolkit.core.diagnostics import CODES, Diagnostic, Severity
from fdstoolkit.core.disk import HEADER_MAGIC, HEADER_SIZE, SIDE_SIZE, SIDES_PER_DISK, Disk, Side
from fdstoolkit.core.parse import parse_side

LOST_IN_FDS: Final = frozenset({"FDS012", "FDS016"})
KEEP_AS_QD: Final = (
    "a .fds keeps these bytes but not where the block ends, since it carries no checksums; "
    "write a .qd to keep the boundary"
)


def has_header(data: bytes) -> bool:
    return (
        len(data) > HEADER_SIZE
        and data[: len(HEADER_MAGIC)] == HEADER_MAGIC
        and (len(data) - HEADER_SIZE) % SIDE_SIZE == 0
    )


def _diagnostic(
    code: str,
    severity: Severity,
    side: int | None = None,
    detail: dict[str, object] | None = None,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        severity=severity,
        message=CODES[code],
        side=side,
        detail=detail or {},
    )


def build_header(side_count: int) -> bytes:
    if not 1 <= side_count <= SIDES_PER_DISK:
        message = f"a side count must be 1 or {SIDES_PER_DISK}, got {side_count}"
        raise ValueError(message)
    return HEADER_MAGIC + bytes([side_count]) + bytes(HEADER_SIZE - len(HEADER_MAGIC) - 1)


def _split_header(data: bytes) -> tuple[int | None, bytes]:
    if has_header(data):
        return data[len(HEADER_MAGIC)], data[HEADER_SIZE:]
    return None, data


def _size_findings(body: bytes) -> tuple[Diagnostic, ...]:
    if not body or not len(body) % SIDE_SIZE:
        return ()
    detail: dict[str, object] = {"size": len(body), "side_size": SIDE_SIZE}
    return (_diagnostic("FDS010", Severity.WARNING, detail=detail),)


def _parsed_sides(body: bytes) -> tuple[tuple[Side, ...], tuple[Diagnostic, ...]]:
    parsed = [
        parse_side(
            body[start : start + SIDE_SIZE],
            has_crc=False,
            side_index=index,
            capacity=min(len(body) - start, SIDE_SIZE),
        )
        for index, start in enumerate(range(0, len(body), SIDE_SIZE))
    ]
    return tuple(side for side, _ in parsed), tuple(item for _, found in parsed for item in found)


def decode(data: bytes) -> tuple[Disk, tuple[Diagnostic, ...]]:
    declared, body = _split_header(data)
    sides, side_findings = _parsed_sides(body)
    findings = (*_size_findings(body), *side_findings)
    if declared is None or declared == len(sides):
        return Disk(sides=sides, header_side_count=declared), findings
    detail: dict[str, object] = {"declared": declared, "found": len(sides)}
    mismatch = _diagnostic("FDS013", Severity.WARNING, detail=detail)
    return Disk(sides=sides, header_side_count=None), (*findings, mismatch)


def target_length(side: Side) -> int:
    return min(SIDE_SIZE, side.capacity)


def encode_side(side: Side) -> bytes:
    content = b"".join(block.payload for block in side.blocks) + side.tail
    target = target_length(side)
    if len(content) >= target:
        return content
    return content.ljust(target, b"\0")


def _lost_lengths(side: Side, index: int) -> list[Diagnostic]:
    lost: list[Diagnostic] = []
    declared: int | None = None
    number = 0
    for block in side.blocks:
        if block.kind is BlockKind.FILE_HEADER:
            header = FileHeader.parse(block.payload)
            declared, number = header.size, header.number
        elif block.kind is BlockKind.FILE_DATA and declared is not None:
            actual = block.size - 1
            if actual != declared:
                code = "FDS016" if actual > declared else "FDS012"
                detail: dict[str, object] = {
                    "declared": declared,
                    "actual": actual,
                    "file": number,
                }
                lost.append(_diagnostic(code, Severity.WARNING, side=index, detail=detail))
    return lost


def export_notes(findings: Sequence[Diagnostic]) -> tuple[str, ...]:
    notes = [finding.render() for finding in findings]
    if any(finding.code in LOST_IN_FDS for finding in findings):
        notes.append(KEEP_AS_QD)
    return tuple(notes)


def encode(disk: Disk, *, headered: bool) -> tuple[bytes, tuple[Diagnostic, ...]]:
    if not disk.sides:
        message = "an image needs at least one side"
        raise ValueError(message)

    findings: list[Diagnostic] = []
    out = bytearray()
    if headered:
        out += build_header(disk.side_count)
    for index, side in enumerate(disk.sides):
        findings.extend(_lost_lengths(side, index))
        encoded = encode_side(side)
        if len(encoded) > SIDE_SIZE:
            findings.append(
                _diagnostic(
                    "FDS011",
                    Severity.ERROR,
                    side=index,
                    detail={"size": len(encoded), "capacity": SIDE_SIZE},
                )
            )
        out += encoded
    return bytes(out), tuple(findings)
