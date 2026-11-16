from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass


class ArchiveError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ArchiveKind:
    what: str
    beyond: str


def _opened(data: bytes, kind: ArchiveKind) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        message = f"{kind.what} is not a zip archive"
        raise ArchiveError(message) from error


def _member(archive: zipfile.ZipFile, name: str, limit: int, kind: ArchiveKind) -> bytes | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > limit:
        message = f"{name} is larger than {kind.beyond}"
        raise ArchiveError(message)
    try:
        with archive.open(info) as member:
            return member.read(limit + 1)
    except zipfile.BadZipFile as error:
        message = f"{name} is damaged inside {kind.what}: {error}"
        raise ArchiveError(message) from error


def member_names(data: bytes, kind: ArchiveKind) -> tuple[str, ...]:
    with _opened(data, kind) as archive:
        return tuple(info.filename for info in archive.infolist() if not info.is_dir())


def read_members(
    data: bytes, names: Sequence[str], *, limit: int, kind: ArchiveKind
) -> dict[str, bytes]:
    with _opened(data, kind) as archive:
        members = {name: _member(archive, name, limit, kind) for name in names}
    return {name: member for name, member in members.items() if member is not None}
