from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from fdstoolkit.core.canon import canonicalise, digest_string
from fdstoolkit.core.disk import Disk
from fdstoolkit.core.diskinfo import RELEASE_PROFILE, MaskProfile
from fdstoolkit.quality.consensus import ConsensusResult, build_consensus

UNKNOWN_CODE: Final = "???"
MIN_FOR_CONSENSUS: Final = 2


@dataclass(frozen=True, slots=True)
class GameKey:
    game_code: str
    version: int
    disk_number: int
    sides: int

    @property
    def label(self) -> str:
        return f"{self.game_code} v{self.version} disk {self.disk_number} ({self.sides} sides)"


@dataclass(frozen=True, slots=True)
class Member:
    name: str
    digest: str


@dataclass(frozen=True, slots=True)
class GroupMaster:
    key: GameKey
    members: tuple[Member, ...]
    digest: str
    variants: int
    consensus: ConsensusResult | None

    @property
    def agreement(self) -> float:
        if not self.members:
            return 0.0
        agreed = sum(1 for member in self.members if member.digest == self.digest)
        return agreed / len(self.members)

    @property
    def unanimous(self) -> bool:
        return self.variants == 1

    @property
    def dissenters(self) -> tuple[str, ...]:
        return tuple(member.name for member in self.members if member.digest != self.digest)


@dataclass(frozen=True, slots=True)
class CorpusReport:
    groups: tuple[GroupMaster, ...]
    profile: MaskProfile

    @property
    def unanimous(self) -> tuple[GroupMaster, ...]:
        return tuple(group for group in self.groups if group.unanimous)

    @property
    def contested(self) -> tuple[GroupMaster, ...]:
        return tuple(group for group in self.groups if not group.unanimous)

    @property
    def agreement(self) -> float:
        if not self.groups:
            return 0.0
        return len(self.unanimous) / len(self.groups)

    @property
    def dumps(self) -> int:
        return sum(len(group.members) for group in self.groups)


def key_of(disk: Disk) -> GameKey:
    info = disk.sides[0].disk_info if disk.sides else None
    if info is None:
        return GameKey(
            game_code=UNKNOWN_CODE,
            version=0,
            disk_number=0,
            sides=disk.side_count,
        )
    return GameKey(
        game_code=info.game_name or UNKNOWN_CODE,
        version=info.game_version,
        disk_number=info.disk_number,
        sides=disk.side_count,
    )


def group_dumps(
    entries: Sequence[tuple[str, Disk]],
) -> dict[GameKey, list[tuple[str, Disk]]]:
    groups: dict[GameKey, list[tuple[str, Disk]]] = {}
    for name, disk in entries:
        groups.setdefault(key_of(disk), []).append((name, disk))
    return groups


def _shape(disk: Disk) -> tuple[int, ...]:
    return (disk.side_count, *(len(side.blocks) for side in disk.sides))


def _consensus(disks: Sequence[Disk]) -> ConsensusResult | None:
    if len(disks) < MIN_FOR_CONSENSUS:
        return None
    reference = _shape(disks[0])
    if any(_shape(disk) != reference for disk in disks[1:]):
        return None
    return build_consensus(disks)


def build_masters(
    entries: Sequence[tuple[str, Disk]],
    *,
    profile: MaskProfile = RELEASE_PROFILE,
) -> CorpusReport:
    groups: list[GroupMaster] = []

    for key, members in group_dumps(entries).items():
        scored = [
            Member(name=name, digest=digest_string(canonicalise(disk, profile)))
            for name, disk in members
        ]
        counts = Counter(member.digest for member in scored)
        winner, _ = counts.most_common(1)[0]
        groups.append(
            GroupMaster(
                key=key,
                members=tuple(scored),
                digest=winner,
                variants=len(counts),
                consensus=_consensus([disk for _, disk in members]),
            )
        )

    groups.sort(key=lambda group: group.key.label)
    return CorpusReport(groups=tuple(groups), profile=profile)
