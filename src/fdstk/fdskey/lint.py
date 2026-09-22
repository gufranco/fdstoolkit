from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final

from fdstk.codecs.fds import HEADER_SIZE, SIDE_SIZE, decode
from fdstk.core.bitstream import EMULATION_BUFFER, emulated_side_size
from fdstk.core.blocks import BlockKind
from fdstk.core.disk import Side
from fdstk.core.diskinfo import VERIFICATION_STRING, DiskInfo

CARD_FILE_SUFFIX: Final = ".fds"
FIRMWARE_BUFFER: Final = EMULATION_BUFFER
COPY_PROGRAM_MEMORY: Final = 29440
MAX_SIDES: Final = 8
MAX_NAME_LENGTH: Final = 255

CODES: Final[Mapping[str, str]] = {
    "FK001": "size is neither a multiple of a side nor a side plus a header",
    "FK002": "the firmware rejects an image whose first block is not a disk info block",
    "FK003": "the disk verification string is missing, so the firmware reports an invalid image",
    "FK004": "a stray block code follows the last block, so the firmware reads a phantom block",
    "FK005": "the gapped image does not fit the emulation buffer",
    "FK006": "a file is larger than the memory the copy program has for one block",
    "FK007": "the filename is not ASCII, so the card filesystem cannot show it",
    "FK008": f"the filename does not end in {CARD_FILE_SUFFIX}",
    "FK009": f"more than {MAX_SIDES} sides",
}


@dataclass(frozen=True, slots=True)
class LintFinding:
    code: str
    message: str
    side: int | None = None
    detail: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))


def _finding(
    code: str,
    side: int | None = None,
    detail: dict[str, object] | None = None,
) -> LintFinding:
    return LintFinding(code=code, message=CODES[code], side=side, detail=detail or {})


def _check_size(data: bytes) -> list[LintFinding]:
    remainder = len(data) % SIDE_SIZE
    if remainder in (0, HEADER_SIZE):
        return []
    return [_finding("FK001", detail={"size": len(data), "remainder": remainder})]


def _check_side(index: int, side: Side, body: bytes) -> list[LintFinding]:
    findings: list[LintFinding] = []
    if not side.is_formatted:
        findings.append(_finding("FK002", side=index))
        return findings

    info = DiskInfo.parse(side.blocks[0].payload)
    if info.verification != VERIFICATION_STRING:
        findings.append(_finding("FK003", side=index))

    used = side.content_size
    start = index * SIDE_SIZE
    remainder = body[start + used : start + SIDE_SIZE]
    if remainder[:1] and remainder[0] in {int(kind) for kind in BlockKind}:
        findings.append(
            _finding("FK004", side=index, detail={"offset": used, "code": remainder[0]})
        )

    emulated = emulated_side_size(side)
    if emulated > FIRMWARE_BUFFER:
        findings.append(
            _finding("FK005", side=index, detail={"size": emulated, "budget": FIRMWARE_BUFFER}),
        )

    findings.extend(
        _finding(
            "FK006",
            side=index,
            detail={"file": header.name, "size": header.size, "budget": COPY_PROGRAM_MEMORY},
        )
        for header in side.file_headers
        if header.size > COPY_PROGRAM_MEMORY
    )

    return findings


def _check_name(name: Path) -> list[LintFinding]:
    findings: list[LintFinding] = []
    if not name.name.isascii() or len(name.name) > MAX_NAME_LENGTH:
        findings.append(_finding("FK007", detail={"name": name.name}))
    if name.suffix.lower() != CARD_FILE_SUFFIX:
        findings.append(_finding("FK008", detail={"name": name.name}))
    return findings


def lint_card_image(data: bytes, *, name: Path) -> tuple[LintFinding, ...]:
    findings = _check_size(data)
    findings.extend(_check_name(name))

    disk, _ = decode(data)
    if disk.side_count > MAX_SIDES:
        findings.append(_finding("FK009", detail={"sides": disk.side_count, "limit": MAX_SIDES}))

    body = data[HEADER_SIZE:] if len(data) % SIDE_SIZE == HEADER_SIZE else data
    for index, side in enumerate(disk.sides):
        findings.extend(_check_side(index, side, body))

    return tuple(findings)
