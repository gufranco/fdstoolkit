from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import parse as parse_xml

from fdstoolkit.identify.hashes import Digests, digests_of


class MatchKind(StrEnum):
    EXACT = "exact"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DatEntry:
    name: str
    size: int
    crc32: str | None
    md5: str | None
    sha1: str | None
    sha256: str | None


@dataclass(frozen=True, slots=True)
class Catalogue:
    name: str
    version: str | None
    entries: tuple[DatEntry, ...]

    def by_sha1(self, digest: str) -> DatEntry | None:
        return self._lookup("sha1", digest)

    def by_sha256(self, digest: str) -> DatEntry | None:
        return self._lookup("sha256", digest)

    def by_md5(self, digest: str) -> DatEntry | None:
        return self._lookup("md5", digest)

    def by_crc32(self, digest: str) -> DatEntry | None:
        return self._lookup("crc32", digest)

    def of_size(self, size: int) -> tuple[DatEntry, ...]:
        return tuple(entry for entry in self.entries if entry.size == size)

    def _lookup(self, field: str, digest: str) -> DatEntry | None:
        wanted = digest.lower()
        for entry in self.entries:
            value = getattr(entry, field)
            if value is not None and value.lower() == wanted:
                return entry
        return None


@dataclass(frozen=True, slots=True)
class Identification:
    kind: MatchKind
    entry: DatEntry | None
    matched_on: str | None
    same_size: tuple[DatEntry, ...]


def _text(element: Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    return element.text.strip()


def _entry_from(game: Element) -> DatEntry | None:
    rom = game.find("rom")
    if rom is None:
        return None
    size = rom.get("size")
    if size is None or not size.isdigit():
        return None
    name = game.get("name") or _text(game.find("description")) or rom.get("name") or "unnamed"
    return DatEntry(
        name=name,
        size=int(size),
        crc32=rom.get("crc"),
        md5=rom.get("md5"),
        sha1=rom.get("sha1"),
        sha256=rom.get("sha256"),
    )


def load_dat(path: Path) -> Catalogue:
    tree = parse_xml(path)
    root: Element | None = tree.getroot()
    if root is None or root.tag != "datafile":
        found = "nothing" if root is None else root.tag
        message = f"{path} is not a DAT file, its root element is {found}"
        raise ValueError(message)

    header = root.find("header")
    entries = [entry for game in root.findall("game") if (entry := _entry_from(game)) is not None]
    entries.sort(key=lambda entry: entry.name)

    return Catalogue(
        name=(_text(header.find("name")) or "") if header is not None else "",
        version=_text(header.find("version")) if header is not None else None,
        entries=tuple(entries),
    )


def _match(digests: Digests, catalogue: Catalogue, suffix: str) -> tuple[DatEntry, str] | None:
    candidates = (
        ("sha256", catalogue.by_sha256(digests.sha256)),
        ("sha1", catalogue.by_sha1(digests.sha1)),
        ("md5", catalogue.by_md5(digests.md5)),
        ("crc32", catalogue.by_crc32(digests.crc32)),
    )
    for algorithm, entry in candidates:
        if entry is not None:
            return entry, f"{algorithm}{suffix}"
    return None


def identify(data: bytes, catalogue: Catalogue) -> Identification:
    digests = digests_of(data)
    found = _match(digests, catalogue, "")
    if found is None and digests.headerless is not None:
        found = _match(digests.headerless, catalogue, " of the headerless image")

    if found is not None:
        entry, matched_on = found
        return Identification(
            kind=MatchKind.EXACT,
            entry=entry,
            matched_on=matched_on,
            same_size=(),
        )

    sizes = catalogue.of_size(digests.size)
    if not sizes and digests.headerless is not None:
        sizes = catalogue.of_size(digests.headerless.size)

    return Identification(
        kind=MatchKind.UNKNOWN,
        entry=None,
        matched_on=None,
        same_size=sizes,
    )
