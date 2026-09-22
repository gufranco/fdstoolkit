from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

SAME_PLACE: Final = 3
MIN_TO_SEPARATE: Final = 2
CLEAN_RETRIES: Final = 3
FRAGILE_RETRIES: Final = 1
NO_RETRIES: Final = 0


class Fault(StrEnum):
    NONE = "none"
    BUS = "bus"
    DRIVE = "drive"
    MEDIA = "media"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class Risk(StrEnum):
    SAFE = "safe"
    FRAGILE = "fragile"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class Observation:
    name: str
    blocks: int
    failed: tuple[int, ...] = ()
    answered: bool = True


@dataclass(frozen=True, slots=True)
class FaultReport:
    fault: Fault
    shared: tuple[int, ...]
    unique: dict[str, tuple[int, ...]]
    disks: int

    @property
    def risk(self) -> Risk:
        if self.fault is Fault.BUS:
            return Risk.STOP
        if self.fault is Fault.NONE:
            return Risk.SAFE
        return Risk.FRAGILE

    @property
    def retries(self) -> int:
        if self.risk is Risk.STOP:
            return NO_RETRIES
        if self.risk is Risk.FRAGILE:
            return FRAGILE_RETRIES
        return CLEAN_RETRIES

    def render(self) -> str:
        if self.fault is Fault.DRIVE:
            return (
                f"{len(self.shared)} place(s) failed on every disk, so this is the drive. "
                "Check the head alignment before reading anything else"
            )
        if self.fault is Fault.MEDIA:
            named = ", ".join(sorted(self.unique))
            return f"the failures sit on {named} alone, so this is the media and not the drive"
        return VERDICTS[self.fault]


VERDICTS: Final[dict[Fault, str]] = {
    Fault.BUS: (
        "the drive stopped answering, which is the drive and not the data. "
        "Stop now and do not put another disk in it"
    ),
    Fault.NONE: "nothing failed, so neither the drive nor the media is implicated",
    Fault.UNKNOWN: (
        "one disk cannot separate a drive fault from a bad disk. Read a second disk and compare"
    ),
    Fault.MIXED: (
        "some failures repeat across disks and some do not, "
        "so the drive and the media are both implicated"
    ),
}


def _near(position: int, others: Sequence[int]) -> bool:
    return any(abs(position - other) <= SAME_PLACE for other in others)


def _split(
    observations: Sequence[Observation],
) -> tuple[list[int], dict[str, tuple[int, ...]]]:
    shared: list[int] = []
    unique: dict[str, tuple[int, ...]] = {}

    for item in observations:
        if not item.failed:
            continue
        others = [other for other in observations if other.name != item.name]
        alone = [
            position
            for position in item.failed
            if not all(_near(position, other.failed) for other in others)
        ]
        everywhere = [
            position
            for position in item.failed
            if all(_near(position, other.failed) for other in others)
        ]
        for position in everywhere:
            if not _near(position, shared):
                shared.append(position)
        if alone:
            unique[item.name] = tuple(alone)

    return shared, unique


def _verdict(shared: Sequence[int], unique: dict[str, tuple[int, ...]]) -> Fault:
    if shared and unique:
        return Fault.MIXED
    if shared:
        return Fault.DRIVE
    return Fault.MEDIA


def classify(observations: Sequence[Observation]) -> FaultReport:
    if not observations:
        message = "a fault needs at least one observation"
        raise ValueError(message)

    disks = len(observations)
    if any(not item.answered for item in observations):
        return FaultReport(fault=Fault.BUS, shared=(), unique={}, disks=disks)

    faulty = [item for item in observations if item.failed]
    if not faulty:
        return FaultReport(fault=Fault.NONE, shared=(), unique={}, disks=disks)

    if disks < MIN_TO_SEPARATE:
        return FaultReport(
            fault=Fault.UNKNOWN,
            shared=(),
            unique={item.name: item.failed for item in faulty},
            disks=disks,
        )

    shared, unique = _split(observations)
    return FaultReport(
        fault=_verdict(shared, unique),
        shared=tuple(sorted(shared)),
        unique=unique,
        disks=disks,
    )
