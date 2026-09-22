from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from fdstk.core.diagnostics import CODES, Diagnostic, Severity
from fdstk.core.disk import Disk, Side

MAX_SIDES: Final = 8


def _game_name(disk: Disk) -> str | None:
    info = disk.sides[0].disk_info if disk.sides else None
    return info.game_name if info is not None else None


def merge(disks: Sequence[Disk]) -> tuple[Disk, tuple[Diagnostic, ...]]:
    if not disks:
        message = "a merge needs at least one image"
        raise ValueError(message)

    sides: list[Side] = []
    for disk in disks:
        sides.extend(disk.sides)
    if len(sides) > MAX_SIDES:
        message = f"a disk set holds at most {MAX_SIDES} sides, the merge would make {len(sides)}"
        raise ValueError(message)

    findings: list[Diagnostic] = []
    names = {name for disk in disks if (name := _game_name(disk)) is not None}
    if len(names) > 1:
        findings.append(
            Diagnostic(
                code="FDS016",
                severity=Severity.INFO,
                message=f"{CODES['FDS016']}: {', '.join(sorted(names))}",
            )
        )

    headered = any(disk.header_side_count is not None for disk in disks)
    return (
        Disk(sides=tuple(sides), header_side_count=len(sides) if headered else None),
        tuple(findings),
    )


def _label(side: Side) -> tuple[str, int, int] | None:
    info = side.disk_info
    if info is None:
        return None
    return (info.game_name, info.disk_number, info.side)


def _starts_a_disk(label: tuple[str, int, int], previous: tuple[str, int, int] | None) -> bool:
    if previous is None:
        return True
    game, number, side = label
    return (game, number) != previous[:2] or side == 0


def unmerge(disk: Disk) -> tuple[tuple[Disk, ...], tuple[Diagnostic, ...]]:
    findings: list[Diagnostic] = []
    parts: list[list[Side]] = []
    previous: tuple[str, int, int] | None = None

    for index, side in enumerate(disk.sides):
        label = _label(side)
        if label is None:
            findings.append(
                Diagnostic(
                    code="FDS017",
                    severity=Severity.WARNING,
                    message=CODES["FDS017"],
                    side=index,
                )
            )
            if parts:
                parts[-1].append(side)
            else:
                parts.append([side])
            continue

        if _starts_a_disk(label, previous):
            parts.append([side])
        else:
            parts[-1].append(side)
        previous = label

    headered = disk.header_side_count is not None
    return (
        tuple(
            Disk(sides=tuple(group), header_side_count=len(group) if headered else None)
            for group in parts
        ),
        tuple(findings),
    )
