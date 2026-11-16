from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdstoolkit.codecs.raw import unpack_detected
from fdstoolkit.drive.align import good_block
from fdstoolkit.drive.captures import Bundle
from fdstoolkit.drive.vote import parse_read
from fdstoolkit.drive.weak import weak_blocks

ZONE_VALUES: Final = 16384
MIN_DISKS: Final = 2
ONE_DISK: Final = (
    "one disk cannot separate the drive from the disk; triage needs the captures of two or "
    "more disks read in the same drive"
)

Place = tuple[int, int]


class Culprit(StrEnum):
    DRIVE = "drive"
    DISK = "disk"
    OPEN = "open"


@dataclass(frozen=True, slots=True)
class Zone:
    side: int
    zone: int
    failing: tuple[str, ...]
    culprit: Culprit

    @property
    def span(self) -> str:
        return (
            f"side {self.side} values {self.zone * ZONE_VALUES}-{(self.zone + 1) * ZONE_VALUES - 1}"
        )


@dataclass(frozen=True, slots=True)
class Triage:
    disks: tuple[str, ...]
    zones: tuple[Zone, ...]

    @property
    def drive_fails(self) -> bool:
        return any(zone.culprit is Culprit.DRIVE for zone in self.zones)


def _side_places(bundle: Bundle, side: int) -> set[Place]:
    captures = bundle.of_side(side)
    reads = [parse_read(unpack_detected(packed)) for packed in captures]
    base = max(reads, key=lambda read: len(read.blocks))
    weak = {entry.block for entry in weak_blocks(captures)}
    bad = {index for index, block in enumerate(base.blocks) if not good_block(block)}
    return {(side, base.regions[index][0] // ZONE_VALUES) for index in weak | bad}


def failing_places(bundle: Bundle) -> frozenset[Place]:
    return frozenset(place for side in bundle.sides for place in _side_places(bundle, side))


def _culprit(failing: int, disks: int) -> Culprit:
    if failing == disks:
        return Culprit.DRIVE
    return Culprit.DISK if failing == 1 else Culprit.OPEN


def triage(bundles: Mapping[str, Bundle]) -> Triage:
    if len(bundles) < MIN_DISKS:
        raise ValueError(ONE_DISK)
    names = tuple(bundles)
    places = {name: failing_places(bundle) for name, bundle in bundles.items()}
    every: list[Place] = sorted(frozenset[Place]().union(*places.values()))
    zones = tuple(
        Zone(
            side=side,
            zone=zone,
            failing=failing,
            culprit=_culprit(len(failing), len(names)),
        )
        for side, zone in every
        for failing in (tuple(name for name in names if (side, zone) in places[name]),)
    )
    return Triage(disks=names, zones=zones)


def _zone_line(zone: Zone, disks: int) -> str:
    named = ", ".join(zone.failing)
    if zone.culprit is Culprit.DRIVE:
        return f"{zone.span}: fails on every disk ({named}), so it is the drive"
    if zone.culprit is Culprit.DISK:
        return f"{zone.span}: fails only on {named}, so it is that disk"
    share = f"{len(zone.failing)} of {disks} disks"
    return f"{zone.span}: fails on {share} ({named}); read more disks to tell"


def triage_lines(found: Triage) -> tuple[str, ...]:
    count = len(found.disks)
    if not found.zones:
        return (f"{count} disks, no position fails on any of them",)
    drive = sum(1 for zone in found.zones if zone.culprit is Culprit.DRIVE)
    heading = (
        f"{count} disks, {drive} position(s) fail on every disk: the drive"
        if drive
        else f"{count} disks, no position fails on every disk: the failures belong to the disks"
    )
    return (heading, *(_zone_line(zone, count) for zone in found.zones))


def triage_payload(found: Triage) -> dict[str, object]:
    return {
        "headline": triage_lines(found)[0],
        "ok": not found.drive_fails,
        "disks": list(found.disks),
        "zones": [
            {
                "side": zone.side,
                "start": zone.zone * ZONE_VALUES,
                "end": (zone.zone + 1) * ZONE_VALUES - 1,
                "culprit": zone.culprit.value,
                "failing": list(zone.failing),
                "finding": _zone_line(zone, len(found.disks)),
            }
            for zone in found.zones
        ],
    }
