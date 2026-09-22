from __future__ import annotations

from pathlib import Path

import pytest

from fdstk.identify.cache import DatCache, cache_root

DAT = """<?xml version="1.0"?>
<datafile>
  <header><name>FDS</name><version>2026-09-01</version></header>
  <game name="Game A">
    <rom name="a.fds" size="65500" crc="12345678" md5="{md5}" sha1="{sha1}"/>
  </game>
</datafile>
"""


def write_dat(path: Path, *, md5: str = "a" * 32, sha1: str = "b" * 40) -> Path:
    path.write_text(DAT.format(md5=md5, sha1=sha1), encoding="utf-8")
    return path


def test_the_cache_root_follows_the_xdg_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    assert cache_root() == tmp_path / "fdstk" / "dat"


def test_the_cache_root_falls_back_to_the_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert cache_root() == tmp_path / ".cache" / "fdstk" / "dat"


def test_a_first_load_is_a_miss_and_writes_the_cache(tmp_path: Path) -> None:
    cache = DatCache(tmp_path / "cache")
    dat = write_dat(tmp_path / "fds.dat")

    catalogue, hit = cache.load(dat)

    assert not hit
    assert catalogue.name == "FDS"
    assert list(cache.entries()) != []


def test_a_second_load_is_a_hit_and_returns_the_same_catalogue(tmp_path: Path) -> None:
    cache = DatCache(tmp_path / "cache")
    dat = write_dat(tmp_path / "fds.dat")
    first, _ = cache.load(dat)

    second, hit = cache.load(dat)

    assert hit
    assert second == first


def test_an_edited_dat_is_reparsed(tmp_path: Path) -> None:
    cache = DatCache(tmp_path / "cache")
    dat = write_dat(tmp_path / "fds.dat")
    cache.load(dat)
    write_dat(dat, sha1="c" * 40)

    catalogue, hit = cache.load(dat)

    assert not hit
    assert catalogue.entries[0].sha1 == "c" * 40


def test_a_corrupt_cache_file_is_treated_as_a_miss(tmp_path: Path) -> None:
    cache = DatCache(tmp_path / "cache")
    dat = write_dat(tmp_path / "fds.dat")
    cache.load(dat)
    for entry in cache.entries():
        entry.write_text("{not json", encoding="utf-8")

    catalogue, hit = cache.load(dat)

    assert not hit
    assert catalogue.name == "FDS"


def test_a_cache_file_missing_its_entries_is_treated_as_a_miss(tmp_path: Path) -> None:
    cache = DatCache(tmp_path / "cache")
    dat = write_dat(tmp_path / "fds.dat")
    cache.load(dat)
    for entry in cache.entries():
        entry.write_text('{"name": "FDS"}', encoding="utf-8")

    _, hit = cache.load(dat)

    assert not hit


def test_clearing_removes_every_cached_catalogue(tmp_path: Path) -> None:
    cache = DatCache(tmp_path / "cache")
    cache.load(write_dat(tmp_path / "fds.dat"))

    removed = cache.clear()

    assert removed == 1
    assert list(cache.entries()) == []


def test_clearing_an_absent_cache_removes_nothing(tmp_path: Path) -> None:
    assert DatCache(tmp_path / "missing").clear() == 0
    assert list(DatCache(tmp_path / "missing").entries()) == []


def test_a_missing_dat_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="file not found"):
        DatCache(tmp_path / "cache").load(tmp_path / "absent.dat")
