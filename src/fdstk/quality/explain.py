from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstk.core.disk import Disk
from fdstk.core.diskinfo import (
    DISK_INFO_FIELDS,
    IDENTITY_FIELDS,
    SHOWA_EPOCH,
    Field,
    bcd_to_int,
)
from fdstk.edit.files import ExtractedFile, extract_files

DATE_FIELDS: Final[frozenset[str]] = frozenset({"manufacturing_date", "rewritten_date"})
TEXT_FIELDS: Final[frozenset[str]] = frozenset({"game_name", "verification"})
DATE_LENGTH: Final = 3
DATE_TEXT_LENGTH: Final = 10


class FileChange(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


@dataclass(frozen=True, slots=True)
class FieldDifference:
    side: int
    field: str
    description: str
    identity: bool
    left: str
    right: str


@dataclass(frozen=True, slots=True)
class FileDifference:
    side: int
    position: int
    name: str
    change: FileChange
    detail: str


@dataclass(frozen=True, slots=True)
class Explanation:
    identical: bool
    same_software: bool
    headline: str
    fields: tuple[FieldDifference, ...]
    files: tuple[FileDifference, ...]


def _date(payload: bytes) -> str | None:
    parts = [bcd_to_int(byte) for byte in payload]
    if len(parts) != DATE_LENGTH or any(part is None for part in parts):
        return None
    year, month, day = (part for part in parts if part is not None)
    return f"{SHOWA_EPOCH + year:04d}-{month:02d}-{day:02d}"


def render_field(field: Field, payload: bytes) -> str:
    if field.name in DATE_FIELDS:
        rendered = _date(payload)
        return rendered if rendered is not None else payload.hex()
    if field.name in TEXT_FIELDS:
        return payload.decode("ascii", errors="replace")
    if field.name == "rewrite_count":
        count = bcd_to_int(payload[0])
        return str(count) if count is not None else payload.hex()
    if field.name == "writer_serial":
        return f"0x{int.from_bytes(payload, 'big'):04x}"
    if field.length == 1:
        return f"0x{payload[0]:02x}"
    return payload.hex()


def _field_differences(left: Disk, right: Disk) -> tuple[FieldDifference, ...]:
    found: list[FieldDifference] = []
    for index, (one, other) in enumerate(zip(left.sides, right.sides, strict=True)):
        first, second = one.disk_info, other.disk_info
        if first is None or second is None:
            continue
        for field in DISK_INFO_FIELDS:
            span = slice(field.offset, field.offset + field.length)
            before, after = first.payload[span], second.payload[span]
            if before == after:
                continue
            found.append(
                FieldDifference(
                    side=index,
                    field=field.name,
                    description=field.description,
                    identity=field.name in IDENTITY_FIELDS,
                    left=render_field(field, before),
                    right=render_field(field, after),
                )
            )
    return tuple(found)


def _key(entry: ExtractedFile) -> tuple[int, int]:
    return (entry.side, entry.position)


def _file_detail(before: ExtractedFile, after: ExtractedFile) -> str | None:
    if before.data != after.data:
        return f"{before.size} bytes against {after.size}"
    if before.name != after.name:
        return f"named {before.name!r} against {after.name!r}"
    if before.address != after.address:
        return f"loads at 0x{before.address:04x} against 0x{after.address:04x}"
    if before.kind is not after.kind:
        return f"{before.kind.name.lower()} against {after.kind.name.lower()}"
    return None


def _file_differences(left: Disk, right: Disk) -> tuple[FileDifference, ...]:
    before = {_key(entry): entry for entry in extract_files(left)}
    after = {_key(entry): entry for entry in extract_files(right)}

    found: list[FileDifference] = []
    for key, entry in before.items():
        if key not in after:
            found.append(
                FileDifference(
                    side=key[0],
                    position=key[1],
                    name=entry.name,
                    change=FileChange.REMOVED,
                    detail=f"{entry.size} bytes",
                )
            )
            continue
        detail = _file_detail(entry, after[key])
        if detail is not None:
            found.append(
                FileDifference(
                    side=key[0],
                    position=key[1],
                    name=entry.name,
                    change=FileChange.CHANGED,
                    detail=detail,
                )
            )

    found.extend(
        FileDifference(
            side=key[0],
            position=key[1],
            name=entry.name,
            change=FileChange.ADDED,
            detail=f"{entry.size} bytes",
        )
        for key, entry in after.items()
        if key not in before
    )

    return tuple(sorted(found, key=lambda entry: (entry.side, entry.position)))


def _reads_as_a_date(rendered: str) -> bool:
    return len(rendered) == DATE_TEXT_LENGTH and rendered[4] == "-"


def _headline(
    *,
    same_software: bool,
    fields: tuple[FieldDifference, ...],
    files: tuple[FileDifference, ...],
) -> str:
    if not fields and not files:
        return "identical"
    if not same_software:
        return "different software"

    parts: list[str] = ["same software"]
    by_name = {difference.field: difference for difference in fields}
    rewritten = by_name.get("rewritten_date")
    if rewritten is not None and _reads_as_a_date(rewritten.right):
        parts.append(f"rewritten {rewritten.right}")
    if "writer_serial" in by_name:
        parts.append(f"writer serial {by_name['writer_serial'].right}")
    if "rewrite_count" in by_name:
        parts.append(f"rewrite count {by_name['rewrite_count'].right}")
    if files:
        parts.append(f"{len(files)} file(s) differ")
    elif len(parts) == 1:
        parts.append(f"{len(fields)} provenance field(s) differ")
    return ", ".join(parts)


def explain(left: Disk, right: Disk) -> Explanation:
    if left.side_count != right.side_count:
        return Explanation(
            identical=False,
            same_software=False,
            headline=f"different disks: {left.side_count} side(s) against {right.side_count}",
            fields=(),
            files=(),
        )

    fields = _field_differences(left, right)
    files = _file_differences(left, right)
    same_software = not any(difference.identity for difference in fields)

    return Explanation(
        identical=not fields and not files,
        same_software=same_software,
        headline=_headline(same_software=same_software, fields=fields, files=files),
        fields=fields,
        files=files,
    )
