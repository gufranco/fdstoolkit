from __future__ import annotations

from enum import StrEnum
from typing import Final

from fdstoolkit.core.blocks import Block
from fdstoolkit.core.crc import encode_crc
from fdstoolkit.core.diagnostics import CODES, Diagnostic, Severity
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.core.parse import parse_side

SIDE_SIZE: Final = 65536
STANDARD_SIDE_SIZES: Final = (65500, 65536)


class CrcMode(StrEnum):
    PRESERVE = "preserve"
    COMPUTE = "compute"
    NULL = "null"


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


def decode(data: bytes) -> tuple[Disk, tuple[Diagnostic, ...]]:
    findings: list[Diagnostic] = []
    if data and len(data) % SIDE_SIZE:
        short_single_side = len(data) < SIDE_SIZE
        findings.append(
            _diagnostic(
                "FDS010",
                Severity.INFO if short_single_side else Severity.WARNING,
                detail={
                    "size": len(data),
                    "side_size": SIDE_SIZE,
                    "short_single_side": short_single_side,
                },
            )
        )

    sides: list[Side] = []
    for index, start in enumerate(range(0, len(data), SIDE_SIZE)):
        chunk = data[start : start + SIDE_SIZE]
        side, side_findings = parse_side(
            chunk,
            has_crc=True,
            side_index=index,
            capacity=min(len(chunk), SIDE_SIZE),
        )
        sides.append(side)
        findings.extend(side_findings)

    return Disk(sides=tuple(sides)), tuple(findings)


def _crc_for(block: Block, mode: CrcMode) -> int:
    if mode is CrcMode.NULL:
        return 0
    if mode is CrcMode.COMPUTE:
        return block.computed_crc
    if block.stored_crc is None:
        return block.computed_crc
    return block.stored_crc


def encode_side(side: Side, mode: CrcMode) -> bytes:
    out = bytearray()
    for block in side.blocks:
        out += block.payload
        out += encode_crc(_crc_for(block, mode))
    out += side.tail
    target = SIDE_SIZE if side.capacity in STANDARD_SIDE_SIZES else side.capacity
    if len(out) >= target:
        return bytes(out)
    return bytes(out).ljust(target, b"\0")


def encode(
    disk: Disk,
    *,
    crc_mode: CrcMode = CrcMode.PRESERVE,
) -> tuple[bytes, tuple[Diagnostic, ...]]:
    if not disk.sides:
        message = "an image needs at least one side"
        raise ValueError(message)

    findings: list[Diagnostic] = []
    out = bytearray()
    for index, side in enumerate(disk.sides):
        encoded = encode_side(side, crc_mode)
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
