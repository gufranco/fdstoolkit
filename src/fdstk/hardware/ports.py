from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

LINK_MARKERS = (
    "device not configured",
    "no such device",
    "not connected",
    "disconnected",
    "stopped answering",
    "no medium",
)

MEDIA_MARKERS = (
    "input/output error",
    "i/o error",
    "media error",
    "unreadable",
    "crc",
)


class ErrorClass(StrEnum):
    LINK = "link"
    MEDIA = "media"
    OTHER = "other"


class FaultKind(StrEnum):
    LINK = "link"
    MEDIA = "media"
    PROTECTED = "protected"
    TIMEOUT = "timeout"
    TRANSIENT = "transient"


SEVERE_KINDS = frozenset({FaultKind.LINK, FaultKind.MEDIA, FaultKind.TIMEOUT})


def classify(message: str) -> ErrorClass:
    lowered = message.lower()
    if any(marker in lowered for marker in LINK_MARKERS):
        return ErrorClass.LINK
    if any(marker in lowered for marker in MEDIA_MARKERS):
        return ErrorClass.MEDIA
    return ErrorClass.OTHER


class HardwareFaultError(Exception):
    def __init__(self, message: str, *, kind: FaultKind) -> None:
        super().__init__(message)
        self.kind = kind

    @property
    def is_severe(self) -> bool:
        return self.kind in SEVERE_KINDS

    @property
    def error_class(self) -> ErrorClass:
        if self.kind is FaultKind.LINK:
            return ErrorClass.LINK
        if self.kind is FaultKind.MEDIA:
            return ErrorClass.MEDIA
        return classify(str(self))


@dataclass(frozen=True, slots=True)
class DriveStatus:
    disk_present: bool
    write_protected: bool
    battery_ok: bool
    ready: bool

    @property
    def blockers(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.disk_present:
            reasons.append("no disk in the drive")
        if self.write_protected:
            reasons.append("disk is write protected")
        if not self.battery_ok:
            reasons.append("battery low")
        if not self.ready:
            reasons.append("drive not ready")
        return tuple(reasons)

    @property
    def can_read(self) -> bool:
        return self.disk_present and self.ready

    @property
    def can_write(self) -> bool:
        return self.can_read and not self.write_protected and self.battery_ok


@dataclass(frozen=True, slots=True)
class BlockRead:
    index: int
    payload: bytes
    crc_ok: bool
    attempts: int

    @property
    def is_marginal(self) -> bool:
        return self.crc_ok and self.attempts > 1

    @property
    def failed(self) -> bool:
        return not self.crc_ok


@runtime_checkable
class DiskReader(Protocol):
    def status(self) -> DriveStatus: ...

    def read_side(self, side: int) -> Iterator[BlockRead]: ...


@runtime_checkable
class DiskWriter(Protocol):
    def status(self) -> DriveStatus: ...

    def write_side(self, side: int, blocks: Sequence[bytes]) -> None: ...
