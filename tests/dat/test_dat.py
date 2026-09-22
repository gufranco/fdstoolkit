from __future__ import annotations

import hashlib
import zlib
from pathlib import Path

import pytest

from fdstk.build.blank import blank_image
from fdstk.identify.dat import Catalogue, DatEntry, MatchKind, identify, load_dat


def entry_xml(name: str, data: bytes, *, sha256: bool = True) -> str:
    digests = (
        f'crc="{zlib.crc32(data):08x}" '
        f'md5="{hashlib.md5(data, usedforsecurity=False).hexdigest()}" '
        f'sha1="{hashlib.sha1(data, usedforsecurity=False).hexdigest()}"'
    )
    if sha256:
        digests += f' sha256="{hashlib.sha256(data).hexdigest()}"'
    return (
        f'  <game name="{name}">\n'
        f"    <description>{name}</description>\n"
        f'    <rom name="{name}.fds" size="{len(data)}" {digests}/>\n'
        f"  </game>\n"
    )


def write_dat(path: Path, games: list[tuple[str, bytes]]) -> Path:
    body = "".join(entry_xml(name, data) for name, data in games)
    path.write_text(
        "<?xml version='1.0'?>\n"
        "<datafile>\n"
        "  <header>\n"
        "    <name>Nintendo - Family Computer Disk System</name>\n"
        "    <version>20260921</version>\n"
        "  </header>\n"
        f"{body}"
        "</datafile>\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def known() -> bytes:
    return blank_image(sides=1, headered=False, formatted=True, game_name="SMB")


@pytest.fixture
def catalogue(tmp_path: Path, known: bytes) -> Catalogue:
    other = blank_image(sides=2, headered=False, formatted=True, game_name="ZEL")
    path = write_dat(
        tmp_path / "fds.dat", [("Known Game (Japan)", known), ("Other (Japan)", other)]
    )
    return load_dat(path)


def test_a_catalogue_reports_its_header(catalogue: Catalogue) -> None:
    assert catalogue.name == "Nintendo - Family Computer Disk System"
    assert catalogue.version == "20260921"
    assert len(catalogue.entries) == 2


def test_an_entry_carries_every_digest(catalogue: Catalogue, known: bytes) -> None:
    entry = catalogue.entries[0]

    assert entry.name == "Known Game (Japan)"
    assert entry.size == len(known)
    assert entry.sha1 == hashlib.sha1(known, usedforsecurity=False).hexdigest()


def test_an_exact_image_is_identified(catalogue: Catalogue, known: bytes) -> None:
    result = identify(known, catalogue)

    assert result.kind is MatchKind.EXACT
    assert result.entry is not None
    assert result.entry.name == "Known Game (Japan)"
    assert result.matched_on == "sha256"


def test_a_headered_image_matches_its_headerless_entry(catalogue: Catalogue) -> None:
    headered = blank_image(sides=1, headered=True, formatted=True, game_name="SMB")

    result = identify(headered, catalogue)

    assert result.kind is MatchKind.EXACT
    assert result.matched_on == "sha256 of the headerless image"


def test_an_unknown_image_reports_the_entries_of_the_same_size(
    catalogue: Catalogue,
    known: bytes,
) -> None:
    altered = bytearray(known)
    altered[0x10:0x13] = b"XYZ"

    result = identify(bytes(altered), catalogue)

    assert result.kind is MatchKind.UNKNOWN
    assert [entry.name for entry in result.same_size] == ["Known Game (Japan)"]


def test_an_image_of_an_unseen_size_has_no_neighbours(catalogue: Catalogue) -> None:
    result = identify(bytes(1234), catalogue)

    assert result.kind is MatchKind.UNKNOWN
    assert result.same_size == ()


def test_a_dat_without_sha256_still_matches_on_sha1(tmp_path: Path, known: bytes) -> None:
    path = tmp_path / "old.dat"
    path.write_text(
        "<?xml version='1.0'?>\n<datafile>\n<header><name>old</name></header>\n"
        + entry_xml("Known Game (Japan)", known, sha256=False)
        + "</datafile>\n",
        encoding="utf-8",
    )

    result = identify(known, load_dat(path))

    assert result.kind is MatchKind.EXACT
    assert result.matched_on == "sha1"


def test_a_catalogue_can_be_looked_up_by_digest(catalogue: Catalogue, known: bytes) -> None:
    digest = hashlib.sha1(known, usedforsecurity=False).hexdigest()

    assert catalogue.by_sha1(digest) is not None
    assert catalogue.by_sha1("0" * 40) is None


def test_a_file_that_is_not_a_dat_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "nope.xml"
    path.write_text("<other/>", encoding="utf-8")

    with pytest.raises(ValueError, match="not a DAT"):
        load_dat(path)


def test_an_entry_without_a_size_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "partial.dat"
    path.write_text(
        "<?xml version='1.0'?>\n<datafile>\n<header><name>partial</name></header>\n"
        '<game name="Broken"><rom name="Broken.fds"/></game>\n'
        "</datafile>\n",
        encoding="utf-8",
    )

    assert load_dat(path).entries == ()


def test_entries_are_sorted_so_reports_are_stable(catalogue: Catalogue) -> None:
    names = [entry.name for entry in catalogue.entries]

    assert names == sorted(names)


def test_an_entry_is_a_value_type() -> None:
    one = DatEntry(name="a", size=1, crc32="b", md5="c", sha1="d", sha256=None)
    other = DatEntry(name="a", size=1, crc32="b", md5="c", sha1="d", sha256=None)

    assert one == other
