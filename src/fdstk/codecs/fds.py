from __future__ import annotations

from typing import Final

from fdstk.core.diagnostics import CODES, Diagnostic, Severity
from fdstk.core.disk import Disk, Side
from fdstk.core.parse import parse_side

MAGIC: Final = b"FDS\x1a"
HEADER_SIZE: Final = 16
SIDE_SIZE: Final = 65500
MAX_SIDES: Final = 255


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
    if not 1 <= side_count <= MAX_SIDES:
        message = f"a side count must be between 1 and {MAX_SIDES}, got {side_count}"
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


def encode(disk: Disk, *, headered: bool) -> tuple[bytes, tuple[Diagnostic, ...]]:
    if not disk.sides:
        message = "an image needs at least one side"
        raise ValueError(message)

    findings: list[Diagnostic] = []
    out = bytearray()
    if headered:
        out += build_header(disk.side_count)
    for index, side in enumerate(disk.sides):
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
