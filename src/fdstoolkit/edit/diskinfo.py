from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.core.diskinfo import FIELDS_BY_NAME, SHOWA_EPOCH

DATE_PATTERN: Final = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
BYTE_MAX: Final = 0xFF


class FieldShape(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"


EDITABLE_FIELDS: Final[Mapping[str, FieldShape]] = {
    "licensee": FieldShape.NUMBER,
    "game_name": FieldShape.TEXT,
    "game_type": FieldShape.NUMBER,
    "game_version": FieldShape.NUMBER,
    "side": FieldShape.NUMBER,
    "disk_number": FieldShape.NUMBER,
    "disk_type_fmc": FieldShape.NUMBER,
    "boot_file": FieldShape.NUMBER,
    "country": FieldShape.NUMBER,
    "manufacturing_date": FieldShape.DATE,
    "rewritten_date": FieldShape.DATE,
    "rewrite_count": FieldShape.NUMBER,
    "actual_side": FieldShape.NUMBER,
    "disk_type_other": FieldShape.NUMBER,
    "disk_version": FieldShape.NUMBER,
}


@dataclass(frozen=True, slots=True)
class FieldChange:
    field: str
    before: str
    after: str


def parse_edit(text: str) -> tuple[str, str]:
    if "=" not in text:
        message = f"an edit is written field=value, got {text}"
        raise ValueError(message)
    name, _, value = text.partition("=")
    return name.strip(), value.strip()


def _to_bcd(value: int) -> int:
    return ((value // 10) << 4) | (value % 10)


def _encode_text(name: str, value: object, length: int) -> bytes:
    text = str(value)
    encoded = text.encode("ascii", errors="replace")
    if len(encoded) > length:
        message = f"{name} holds {length} byte(s), got {len(encoded)}"
        raise ValueError(message)
    return encoded.ljust(length, b" ")


def _encode_number(name: str, value: object) -> bytes:
    number = int(str(value), 0) if isinstance(value, str) else int(value)  # type: ignore[arg-type]
    if not 0 <= number <= BYTE_MAX:
        message = f"{name} is a single byte, so it is between 0 and 255, got {number}"
        raise ValueError(message)
    return bytes([number])


def _encode_date(name: str, value: object) -> bytes:
    match = DATE_PATTERN.match(str(value))
    if match is None:
        message = f"{name} is written YYYY-MM-DD, got {value}"
        raise ValueError(message)
    year, month, day = (int(part) for part in match.groups())
    return bytes([_to_bcd(year - SHOWA_EPOCH), _to_bcd(month), _to_bcd(day)])


def _encode(name: str, value: object, length: int) -> bytes:
    shape = EDITABLE_FIELDS[name]
    if shape is FieldShape.TEXT:
        return _encode_text(name, value, length)
    if shape is FieldShape.DATE:
        return _encode_date(name, value)
    return _encode_number(name, value)


def _describe(payload: bytes, name: str) -> str:
    field = FIELDS_BY_NAME[name]
    raw = payload[field.offset : field.offset + field.length]
    shape = EDITABLE_FIELDS[name]
    if shape is FieldShape.TEXT:
        return raw.decode("ascii", errors="replace").rstrip(" \0")
    if shape is FieldShape.DATE:
        return raw.hex()
    return str(raw[0])


def apply_edits(
    disk: Disk,
    *,
    side: int,
    edits: Mapping[str, object],
) -> tuple[Disk, tuple[FieldChange, ...]]:
    if not 0 <= side < disk.side_count:
        message = f"the image has no side {side}"
        raise ValueError(message)

    target = disk.sides[side]
    if not target.is_formatted:
        message = f"side {side} carries no disk information block, so there is nothing to edit"
        raise ValueError(message)

    payload = bytearray(target.blocks[0].payload)
    changes: list[FieldChange] = []

    for name, value in edits.items():
        field = FIELDS_BY_NAME.get(name)
        if field is None:
            known = ", ".join(sorted(EDITABLE_FIELDS))
            message = f"unknown field {name}, editable fields are {known}"
            raise ValueError(message)
        if name not in EDITABLE_FIELDS:
            message = f"{name} is not editable, because changing it would break the disk"
            raise ValueError(message)

        before = _describe(bytes(payload), name)
        payload[field.offset : field.offset + field.length] = _encode(name, value, field.length)
        changes.append(
            FieldChange(field=name, before=before, after=_describe(bytes(payload), name)),
        )

    if not changes:
        return disk, ()

    blocks = (
        Block(kind=BlockKind.DISK_INFO, payload=bytes(payload)),
        *target.blocks[1:],
    )
    sides = list(disk.sides)
    sides[side] = Side(blocks=blocks, tail=target.tail, capacity=target.capacity)
    return Disk(sides=tuple(sides), header_side_count=disk.header_side_count), tuple(changes)
