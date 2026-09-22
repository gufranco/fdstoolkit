from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from fdstoolkit.core.canon import canonicalise, digest_string
from fdstoolkit.core.disk import Disk
from fdstoolkit.core.diskinfo import PROFILES, MaskProfile
from fdstoolkit.master.corpus import CorpusReport, GameKey, key_of

SCHEMA: Final = "fdstoolkit.reference/v1"


class Verdict(StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ReferenceEntry:
    game_code: str
    version: int
    disk_number: int
    sides: int
    digest: str
    dumps: int
    agreement: float
    names: tuple[str, ...] = ()

    @property
    def key(self) -> GameKey:
        return GameKey(
            game_code=self.game_code,
            version=self.version,
            disk_number=self.disk_number,
            sides=self.sides,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "game_code": self.game_code,
            "version": self.version,
            "disk_number": self.disk_number,
            "sides": self.sides,
            "digest": self.digest,
            "dumps": self.dumps,
            "agreement": round(self.agreement, 6),
            "names": list(self.names),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReferenceEntry:
        return cls(
            game_code=str(payload["game_code"]),
            version=int(payload["version"]),
            disk_number=int(payload["disk_number"]),
            sides=int(payload["sides"]),
            digest=str(payload["digest"]),
            dumps=int(payload["dumps"]),
            agreement=float(payload["agreement"]),
            names=tuple(str(name) for name in payload.get("names", ())),
        )


@dataclass(frozen=True, slots=True)
class Match:
    verdict: Verdict
    entry: ReferenceEntry | None
    digest: str

    @property
    def matched(self) -> bool:
        return self.verdict is Verdict.MATCH


@dataclass(frozen=True, slots=True)
class ReferenceSet:
    version: str
    profile: MaskProfile
    entries: tuple[ReferenceEntry, ...]

    def by_digest(self, digest: str) -> ReferenceEntry | None:
        for entry in self.entries:
            if entry.digest == digest:
                return entry
        return None

    def by_key(self, key: GameKey) -> ReferenceEntry | None:
        for entry in self.entries:
            if entry.key == key:
                return entry
        return None

    def verify(self, disk: Disk) -> Match:
        digest = digest_string(canonicalise(disk, self.profile))
        exact = self.by_digest(digest)
        if exact is not None:
            return Match(verdict=Verdict.MATCH, entry=exact, digest=digest)
        expected = self.by_key(key_of(disk))
        if expected is not None:
            return Match(verdict=Verdict.MISMATCH, entry=expected, digest=digest)
        return Match(verdict=Verdict.UNKNOWN, entry=None, digest=digest)

    def to_json(self, *, indent: int = 2) -> str:
        payload = {
            "schema": SCHEMA,
            "version": self.version,
            "profile": self.profile.name,
            "entries": [entry.as_dict() for entry in self.entries],
        }
        return json.dumps(payload, indent=indent) + "\n"

    @classmethod
    def from_json(cls, text: str) -> ReferenceSet:
        payload = json.loads(text)
        if payload.get("schema") != SCHEMA:
            message = f"not a {SCHEMA} document"
            raise ValueError(message)
        name = str(payload["profile"])
        profile = PROFILES.get(name)
        if profile is None:
            message = f"unknown profile {name}"
            raise ValueError(message)
        return cls(
            version=str(payload["version"]),
            profile=profile,
            entries=tuple(ReferenceEntry.from_dict(item) for item in payload["entries"]),
        )


def reference_from(report: CorpusReport, *, version: str) -> ReferenceSet:
    entries = tuple(
        ReferenceEntry(
            game_code=group.key.game_code,
            version=group.key.version,
            disk_number=group.key.disk_number,
            sides=group.key.sides,
            digest=group.digest,
            dumps=len(group.members),
            agreement=group.agreement,
            names=tuple(sorted(member.name for member in group.members)),
        )
        for group in report.groups
    )
    return ReferenceSet(version=version, profile=report.profile, entries=entries)
