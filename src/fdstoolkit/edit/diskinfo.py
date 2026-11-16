from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.build.fields import as_int
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.core.diskinfo import FIELDS_BY_NAME
from fdstoolkit.core.showa import encode_date, parse_date

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


def _encode_text(name: str, value: object, length: int) -> bytes:
    text = str(value)
    encoded = text.encode("ascii", errors="replace")
    if len(encoded) > length:
        message = f"{name} holds {length} byte(s), got {len(encoded)}"
        raise ValueError(message)
    return encoded.ljust(length, b" ")


def _encode_number(name: str, value: object) -> bytes:
    number = as_int(value, key=name, where="")
    if not 0 <= number <= BYTE_MAX:
        message = f"{name} is a single byte, so it is between 0 and 255, got {number}"
        raise ValueError(message)
    return bytes([number])


def _encode_date(name: str, value: object) -> bytes:
    return encode_date(*parse_date(str(value), field=name))


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


def _edited(payload: bytes, name: str, value: object) -> tuple[bytes, FieldChange]:
    field = FIELDS_BY_NAME.get(name)
    if field is None:
        known = ", ".join(sorted(EDITABLE_FIELDS))
        message = f"unknown field {name}, editable fields are {known}"
        raise ValueError(message)
    if name not in EDITABLE_FIELDS:
        message = f"{name} is not editable, because changing it would break the disk"
        raise ValueError(message)
    end = field.offset + field.length
    changed = payload[: field.offset] + _encode(name, value, field.length) + payload[end:]
    change = FieldChange(
        field=name, before=_describe(payload, name), after=_describe(changed, name)
    )
    return changed, change


def _editable_side(disk: Disk, side: int) -> Side:
    if not 0 <= side < disk.side_count:
        message = f"the image has no side {side}"
        raise ValueError(message)
    target = disk.sides[side]
    if not target.is_formatted:
        message = f"side {side} carries no disk information block, so there is nothing to edit"
        raise ValueError(message)
    return target


def apply_edits(
    disk: Disk,
    *,
    side: int,
    edits: Mapping[str, object],
) -> tuple[Disk, tuple[FieldChange, ...]]:
    target = _editable_side(disk, side)
    payload = target.blocks[0].payload
    changes: list[FieldChange] = []
    for name, value in edits.items():
        payload, change = _edited(payload, name, value)
        changes.append(change)
    if not changes:
        return disk, ()
    blocks = (Block(kind=BlockKind.DISK_INFO, payload=payload), *target.blocks[1:])
    edited = Side(blocks=blocks, tail=target.tail, capacity=target.capacity)
    sides = tuple(edited if index == side else entry for index, entry in enumerate(disk.sides))
    return Disk(sides=sides, header_side_count=disk.header_side_count), tuple(changes)
