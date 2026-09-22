from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fdstk.core.disk import Disk
from fdstk.core.diskinfo import DiskInfo


class Origin(StrEnum):
    FACTORY = "factory"
    REWRITTEN = "rewritten"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SideProvenance:
    index: int
    origin: Origin
    manufacturing_date: tuple[int, int, int] | None
    rewritten_date: tuple[int, int, int] | None
    writer_serial: int | None
    rewrite_count: int | None
    disk_type: int | None
    disk_version: int | None
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "disk_type": self.disk_type,
            "disk_version": self.disk_version,
            "index": self.index,
            "manufacturing_date": list(self.manufacturing_date)
            if self.manufacturing_date
            else None,
            "notes": list(self.notes),
            "origin": str(self.origin),
            "rewrite_count": self.rewrite_count,
            "rewritten_date": list(self.rewritten_date) if self.rewritten_date else None,
            "writer_serial": self.writer_serial,
        }


@dataclass(frozen=True, slots=True)
class ProvenanceReport:
    sides: tuple[SideProvenance, ...]


def _origin_of(info: DiskInfo) -> Origin:
    count = info.rewrite_count
    if count is None:
        return Origin.UNKNOWN
    stamped = info.raw("rewritten_date") != bytes(3)
    moved = stamped and info.rewritten_date != info.manufacturing_date
    if count > 0 or info.writer_serial != 0 or moved:
        return Origin.REWRITTEN
    return Origin.FACTORY


def _notes_for(info: DiskInfo, origin: Origin) -> tuple[str, ...]:
    notes: list[str] = []
    if info.manufacturing_date is None:
        notes.append("the manufacturing date is not valid BCD")
    if info.rewritten_date is None:
        notes.append("the rewritten date is not valid BCD")
    if info.rewrite_count is None:
        notes.append("the rewrite count is not valid BCD")
    if origin is Origin.REWRITTEN and info.writer_serial == 0:
        notes.append("rewritten but carries no Disk Writer serial")
    if info.rewrite_count == 0 and origin is Origin.REWRITTEN:
        notes.append("rewritten but the rewrite count is zero")
    return tuple(notes)


def provenance_of(disk: Disk) -> ProvenanceReport:
    sides: list[SideProvenance] = []
    for index, side in enumerate(disk.sides):
        info = side.disk_info
        if info is None:
            sides.append(
                SideProvenance(
                    index=index,
                    origin=Origin.UNKNOWN,
                    manufacturing_date=None,
                    rewritten_date=None,
                    writer_serial=None,
                    rewrite_count=None,
                    disk_type=None,
                    disk_version=None,
                    notes=("the side carries no disk information block",),
                )
            )
            continue

        origin = _origin_of(info)
        sides.append(
            SideProvenance(
                index=index,
                origin=origin,
                manufacturing_date=info.manufacturing_date,
                rewritten_date=info.rewritten_date,
                writer_serial=info.writer_serial,
                rewrite_count=info.rewrite_count,
                disk_type=info.disk_type,
                disk_version=info.disk_version,
                notes=_notes_for(info, origin),
            )
        )

    return ProvenanceReport(sides=tuple(sides))
