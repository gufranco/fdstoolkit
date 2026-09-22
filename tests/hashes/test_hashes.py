from __future__ import annotations

import hashlib
import zlib

from fdstoolkit.codecs.fds import SIDE_SIZE
from fdstoolkit.identify.hashes import Digests, digests_of, retroachievements_hash, side_digests


def headered(sides: int = 1) -> bytes:
    return b"FDS\x1a" + bytes([sides]) + bytes(11) + bytes(SIDE_SIZE * sides)


def test_digests_cover_the_four_algorithms_the_databases_use() -> None:
    data = b"hello"

    result = digests_of(data)

    assert result.crc32 == f"{zlib.crc32(data):08x}"
    assert result.md5 == hashlib.md5(data, usedforsecurity=False).hexdigest()
    assert result.sha1 == hashlib.sha1(data, usedforsecurity=False).hexdigest()
    assert result.sha256 == hashlib.sha256(data).hexdigest()


def test_digests_report_the_size_they_covered() -> None:
    assert digests_of(bytes(10)).size == 10


def test_a_headered_image_is_hashed_both_ways() -> None:
    data = headered()

    result = digests_of(data)

    assert result.size == len(data)
    assert result.headerless is not None
    assert result.headerless.size == SIDE_SIZE
    assert result.headerless.sha1 == hashlib.sha1(data[16:], usedforsecurity=False).hexdigest()


def test_a_headerless_image_has_no_second_view() -> None:
    assert digests_of(bytes(SIDE_SIZE)).headerless is None


def test_each_side_is_hashed_on_its_own() -> None:
    data = bytes(SIDE_SIZE) + bytes([0xFF]) * SIDE_SIZE

    per_side = side_digests(data, SIDE_SIZE)

    assert len(per_side) == 2
    assert per_side[0].sha256 != per_side[1].sha256
    assert all(entry.size == SIDE_SIZE for entry in per_side)


def test_a_short_trailing_side_is_still_hashed() -> None:
    per_side = side_digests(bytes(SIDE_SIZE + 100), SIDE_SIZE)

    assert len(per_side) == 2
    assert per_side[1].size == 100


def test_digests_render_as_a_stable_mapping() -> None:
    rendered = digests_of(b"hello").as_dict()

    assert list(rendered) == ["size", "crc32", "md5", "sha1", "sha256"]


def test_two_runs_produce_the_same_digests() -> None:
    assert digests_of(b"hello") == digests_of(b"hello")


def test_digests_are_a_value_type() -> None:
    one = Digests(size=1, crc32="a", md5="b", sha1="c", sha256="d")
    other = Digests(size=1, crc32="a", md5="b", sha1="c", sha256="d")

    assert one == other


def test_the_retroachievements_hash_skips_an_fwnes_header() -> None:
    body = bytes(range(256)) * 4
    headered = b"FDS\x1a" + bytes(12) + body

    assert retroachievements_hash(headered) == hashlib.md5(body, usedforsecurity=False).hexdigest()


def test_the_retroachievements_hash_covers_a_headerless_file_whole() -> None:
    body = bytes(range(256)) * 4

    assert retroachievements_hash(body) == hashlib.md5(body, usedforsecurity=False).hexdigest()
