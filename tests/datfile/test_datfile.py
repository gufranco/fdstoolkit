from __future__ import annotations

from hashlib import sha1
from pathlib import Path

import pytest
from defusedxml.ElementTree import fromstring

from fdstoolkit.identify.dat import load_dat
from fdstoolkit.identify.datfile import build_dat


def _entries() -> list[tuple[str, bytes]]:
    return [("Falsion (Japan).fds", b"one"), ("Metroid (Japan).fds", b"two")]


def test_a_dat_names_its_header() -> None:
    text = build_dat(_entries(), name="FDS", version="2026-09-22")

    root = fromstring(text)
    header = root.find("header")
    assert header is not None
    assert header.findtext("name") == "FDS"
    assert header.findtext("version") == "2026-09-22"


def test_a_dat_carries_one_game_per_entry() -> None:
    root = fromstring(build_dat(_entries(), name="FDS", version="1"))

    assert len(root.findall("game")) == 2


def test_a_game_carries_the_digests_of_its_file() -> None:
    root = fromstring(build_dat([("Falsion (Japan).fds", b"one")], name="FDS", version="1"))

    rom = root.find("game/rom")
    assert rom is not None
    assert rom.get("size") == "3"
    assert rom.get("crc")
    assert rom.get("md5")
    assert rom.get("sha1")
    assert rom.get("sha256")


def test_the_game_name_drops_the_extension() -> None:
    root = fromstring(build_dat([("Falsion (Japan).fds", b"one")], name="FDS", version="1"))

    game = root.find("game")
    assert game is not None
    assert game.get("name") == "Falsion (Japan)"
    assert game.findtext("description") == "Falsion (Japan)"


def test_the_rom_keeps_its_file_name() -> None:
    root = fromstring(build_dat([("Falsion (Japan).fds", b"one")], name="FDS", version="1"))

    rom = root.find("game/rom")
    assert rom is not None
    assert rom.get("name") == "Falsion (Japan).fds"


def test_a_description_and_author_can_be_given() -> None:
    text = build_dat(
        _entries(),
        name="FDS",
        version="1",
        description="A set",
        author="Someone",
    )

    root = fromstring(text)
    header = root.find("header")
    assert header is not None
    assert header.findtext("description") == "A set"
    assert header.findtext("author") == "Someone"


def test_games_come_out_in_name_order() -> None:
    root = fromstring(build_dat(list(reversed(_entries())), name="FDS", version="1"))

    names = [game.get("name") or "" for game in root.findall("game")]
    assert names == sorted(names)


def test_a_dat_with_no_entry_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one entry"):
        build_dat([], name="FDS", version="1")


def test_the_result_parses_back_through_the_reader(tmp_path: Path) -> None:

    path = tmp_path / "set.dat"
    path.write_text(build_dat(_entries(), name="FDS", version="1"), encoding="utf-8")

    catalogue = load_dat(path)

    assert catalogue.name == "FDS"
    assert len(catalogue.entries) == 2


def test_a_round_trip_finds_an_entry_by_its_digest(tmp_path: Path) -> None:

    path = tmp_path / "set.dat"
    path.write_text(build_dat([("A.fds", b"one")], name="FDS", version="1"), encoding="utf-8")

    catalogue = load_dat(path)

    assert catalogue.by_sha1(sha1(b"one", usedforsecurity=False).hexdigest()) is not None
