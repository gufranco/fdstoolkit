from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final

from fdstoolkit.build.fdspacker import (
    COUNTRIES,
    DISK_TYPES,
    DISK_TYPES_OTHER,
    FILE_KINDS,
    FIRST_UNKNOWNS,
    MIDDLE_UNKNOWNS,
    SIDES,
    TEXT_ENCODING,
)
from fdstoolkit.core.blocks import Block, BlockKind, FileHeader
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.core.diskinfo import FIELDS_BY_NAME, SHOWA_EPOCH, VERIFICATION_STRING, to_bcd

MANIFEST_NAME: Final = "diskinfo.json"
UNSAFE_NAME: Final = re.compile(r"[^A-Za-z0-9_-]")
PRINTABLE: Final = range(0x20, 0x7F)
LOST_REWRITE_COUNT: Final = 0xFF
EXTENSIONS: Final[Mapping[int, str]] = {0: "prg", 1: "chr", 2: "nt"}
JSON_INDENT: Final = 2


class FdsPackerExportError(ValueError):
    pass


def _refuse(side: int, reason: str) -> FdsPackerExportError:
    return FdsPackerExportError(
        f"side {side} cannot be written as an FDSPacker manifest: {reason}, "
        "and FDSPacker would rebuild a different disk"
    )


def _field(info: bytes, name: str) -> bytes:
    field = FIELDS_BY_NAME[name]
    return info[field.offset : field.offset + field.length]


def _hex(value: int) -> str:
    return f"${value:02X}"


def _name_of(value: int, names: Mapping[str, int]) -> str:
    for name, number in names.items():
        if number == value:
            return name
    return _hex(value)


def _digits(value: int) -> int:
    return (value >> 4) * 10 + (value & 0x0F)


def _date(raw: bytes, *, field: str, side: int) -> str | None:
    if not any(raw):
        return None
    year, month, day = (_digits(value) for value in raw)
    encoded = tuple(to_bcd(value) for value in (year, month, day))
    try:
        written = date(year + SHOWA_EPOCH, month, day)
    except ValueError:
        written = None
    if written is None or encoded != tuple(raw):
        raise _refuse(side, f"{field} holds {raw.hex(' ')}, which is not a date")
    return written.isoformat()


def _rewrite_count(value: int, *, side: int) -> int:
    count = _digits(value)
    if value == LOST_REWRITE_COUNT or to_bcd(count) != value:
        raise _refuse(side, f"the rewrite count byte is {value:#04x}, which is not a count")
    return count


def _game_name(raw: bytes) -> str | None:
    if not any(raw):
        return None
    return raw.decode(TEXT_ENCODING).rstrip("\0")


def _game_type(value: int) -> str:
    return chr(value) if value in PRINTABLE else _hex(value)


def _identity(info: bytes) -> dict[str, object]:
    return {
        "licensee_code": _hex(info[0x0F]),
        "game_name": _game_name(_field(info, "game_name")),
        "game_type": _game_type(info[0x13]),
        "game_version": info[0x14],
        "disk_side": _name_of(info[0x15], SIDES),
        "disk_number": info[0x16],
        "disk_type": _name_of(info[0x17], DISK_TYPES),
        "unknown01": _hex(info[0x18]),
        "boot_file": info[0x19],
    }


def _unknowns(info: bytes, names: tuple[tuple[str, int], ...], start: int) -> dict[str, object]:
    return {name: _hex(info[start + index]) for index, (name, _) in enumerate(names)}


def _provenance(info: bytes, *, side: int) -> dict[str, object]:
    serial = int.from_bytes(_field(info, "writer_serial"), "little")
    return {
        "rewritten_date": _date(_field(info, "rewritten_date"), field="rewritten_date", side=side),
        "unknown16": _hex(info[0x2F]),
        "unknown17": _hex(info[0x30]),
        "disk_writer_serial_number": f"${serial:04X}",
        "unknown18": _hex(info[0x33]),
        "disk_rewrite_count": _rewrite_count(info[0x34], side=side),
        "actual_disk_side": _name_of(info[0x35], SIDES),
        "disk_type_other": _name_of(info[0x36], DISK_TYPES_OTHER),
        "disk_version": _hex(info[0x37]),
    }


def _info(info: bytes, *, side: int) -> dict[str, object]:
    if _field(info, "verification") != VERIFICATION_STRING:
        raise _refuse(side, "its verification string is not *NINTENDO-HVC*")
    made = _date(_field(info, "manufacturing_date"), field="manufacturing_date", side=side)
    return {
        **_identity(info),
        **_unknowns(info, FIRST_UNKNOWNS, 0x1A),
        "manufacturing_date": made,
        "country_code": _name_of(info[0x22], COUNTRIES),
        **_unknowns(info, MIDDLE_UNKNOWNS, 0x23),
        **_provenance(info, side=side),
    }


def _data_path(header: FileHeader, *, side: int, position: int) -> str:
    stem = UNSAFE_NAME.sub("_", header.name) or "file"
    extension = EXTENSIONS.get(header.raw_kind, "bin")
    return f"side{side}-{position:02d}-{stem}.{extension}"


def _pairs(side: Side, *, number: int) -> list[tuple[Block, Block]]:
    blocks = side.blocks
    leading = tuple(block.kind for block in blocks[:2])
    if leading != (BlockKind.DISK_INFO, BlockKind.FILE_AMOUNT):
        raise _refuse(number, "it does not open with a disk information and a file amount block")
    rest = blocks[2:]
    headers, datas = rest[0::2], rest[1::2]
    shaped = len(headers) == len(datas) and all(
        header.kind is BlockKind.FILE_HEADER and data.kind is BlockKind.FILE_DATA
        for header, data in zip(headers, datas, strict=True)
    )
    if not shaped:
        raise _refuse(number, "its blocks after the file amount are not header and data pairs")
    if side.tail.strip(b"\0"):
        raise _refuse(number, "it carries bytes after its last block")
    return list(zip(headers, datas, strict=True))


def _file(
    header_block: Block, data_block: Block, *, side: int, position: int
) -> tuple[dict[str, object], tuple[str, bytes]]:
    header = FileHeader.parse(header_block.payload)
    data = data_block.payload[1:]
    if header.size != len(data):
        reason = f"file {position} states {header.size} bytes and holds {len(data)}"
        raise _refuse(side, reason)
    path = _data_path(header, side=side - 1, position=position - 1)
    entry: dict[str, object] = {
        "file_number": header.number,
        "file_indicate_code": header.file_id,
        "file_name": header.raw_name.decode(TEXT_ENCODING).rstrip("\0"),
        "file_address": f"${header.address:04X}",
        "file_kind": _name_of(header.raw_kind, FILE_KINDS),
        "data": path,
    }
    return entry, (path, data)


def _side(side: Side, *, number: int) -> tuple[dict[str, object], list[tuple[str, bytes]]]:
    pairs = _pairs(side, number=number)
    files = [
        _file(header, data, side=number, position=position)
        for position, (header, data) in enumerate(pairs, start=1)
    ]
    entry = {
        **_info(side.blocks[0].payload, side=number),
        "file_amount": side.blocks[1].payload[1],
        "files": [item for item, _ in files],
    }
    return entry, [written for _, written in files]


@dataclass(frozen=True, slots=True)
class FdsPackerExport:
    manifest: Mapping[str, object]
    files: tuple[tuple[str, bytes], ...]

    @classmethod
    def of(cls, disk: Disk) -> FdsPackerExport:
        sides = [_side(side, number=number) for number, side in enumerate(disk.sides, start=1)]
        return cls(
            manifest={"sides": [entry for entry, _ in sides]},
            files=tuple(written for _, files in sides for written in files),
        )

    def text(self) -> str:
        return json.dumps(self.manifest, indent=JSON_INDENT, ensure_ascii=False) + "\n"
