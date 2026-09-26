from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from fdstoolkit.core.blocks import BlockKind, FileHeader
from fdstoolkit.core.diagnostics import CODES, Diagnostic, Severity
from fdstoolkit.core.disk import SIDES_PER_DISK, Disk, Side
from fdstoolkit.core.parse import parse_side

MAGIC: Final = b"FDS\x1a"
HEADER_SIZE: Final = 16
LOST_IN_FDS: Final = frozenset({"FDS012", "FDS016"})
KEEP_AS_QD: Final = (
    "a .fds keeps these bytes but not where the block ends, since it carries no checksums; "
    "write a .qd to keep the boundary"
)
SIDE_SIZE: Final = 65500


def has_header(data: bytes) -> bool:
    return (
        len(data) > HEADER_SIZE
        and data[: len(MAGIC)] == MAGIC
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
    return MAGIC + bytes([side_count]) + bytes(HEADER_SIZE - len(MAGIC) - 1)


def decode(data: bytes) -> tuple[Disk, tuple[Diagnostic, ...]]:
    findings: list[Diagnostic] = []
    declared: int | None = None
    body = data
    if has_header(data):
        declared = data[len(MAGIC)]
        body = data[HEADER_SIZE:]

    if body and len(body) % SIDE_SIZE:
        findings.append(
            _diagnostic(
                "FDS010",
                Severity.WARNING,
                detail={"size": len(body), "side_size": SIDE_SIZE},
            )
        )

    sides: list[Side] = []
    for index, start in enumerate(range(0, len(body), SIDE_SIZE)):
        chunk = body[start : start + SIDE_SIZE]
        side, side_findings = parse_side(
            chunk,
            has_crc=False,
            side_index=index,
            capacity=min(len(chunk), SIDE_SIZE),
        )
        sides.append(side)
        findings.extend(side_findings)

    if declared is not None and declared != len(sides):
        findings.append(
            _diagnostic(
                "FDS013",
                Severity.WARNING,
                detail={"declared": declared, "found": len(sides)},
            )
        )
        declared = None

    return Disk(sides=tuple(sides), header_side_count=declared), tuple(findings)


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
