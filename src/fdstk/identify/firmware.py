from __future__ import annotations

import hashlib
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

BIOS_SIZE: Final = 0x2000
INES_HEADER: Final = 16
INES_MAGIC: Final = b"NES\x1a"


MAME_SOURCE: Final = "MAME disksys.cpp and nes.cpp"
VARIANT_SOURCE: Final = "a No-Intro-named set, not listed by MAME"


@dataclass(frozen=True, slots=True)
class Revision:
    name: str
    crc32: str
    sha1: str
    mame_name: str | None
    source: str = MAME_SOURCE


KNOWN_REVISIONS: Final[Mapping[str, Revision]] = {
    "1c7ae5d5": Revision(
        name="Rev 01",
        crc32="1c7ae5d5",
        sha1="af5af53f66982e749643fdf8b2acbb7d4d3ed229",
        mame_name="rp2c33-01.bin",
    ),
    "5e607dcf": Revision(
        name="Rev 01A",
        crc32="5e607dcf",
        sha1="57fe1bdee955bb48d357e463ccbf129496930b62",
        mame_name="rp2c33a-01a.bin",
    ),
    "4df24a6c": Revision(
        name="Rev 02",
        crc32="4df24a6c",
        sha1="e4e41472c454f928e53eb10e0509bf7d1146ecc1",
        mame_name="rp2c33a-02.bin",
    ),
}

KNOWN_VARIANTS: Final[Mapping[str, Revision]] = {
    "17e30673": Revision(
        name="Rev 1, 3DS Virtual Console",
        crc32="17e30673",
        sha1="176872eb7867eb82cab945bb1f473666a72ff2e7",
        mame_name=None,
        source=VARIANT_SOURCE,
    ),
    "34e2b2c7": Revision(
        name="Rev 1, 3DS Virtual Console, alternate",
        crc32="34e2b2c7",
        sha1="b5c73b2e48c979ebb86f2a9cfbc6b30cbc55a5ab",
        mame_name=None,
        source=VARIANT_SOURCE,
    ),
    "0ba8d953": Revision(
        name="Rev 1, Animal Crossing",
        crc32="0ba8d953",
        sha1="311cba745b56b5bc49fb88bfc9f355db18f4db9a",
        mame_name=None,
        source=VARIANT_SOURCE,
    ),
    "7d8f0c3c": Revision(
        name="Rev 1, Game & Watch - Super Mario Bros.",
        crc32="7d8f0c3c",
        sha1="031a60a177d7db32caff2a235d6ee644e52c1a31",
        mame_name=None,
        source=VARIANT_SOURCE,
    ),
}

NESTOPIA_KNOWN: Final[frozenset[str]] = frozenset({"5e607dcf", "4df24a6c"})


@dataclass(frozen=True, slots=True)
class BiosReport:
    size: int
    exact_size: bool
    offset: int | None
    crc32: str | None
    sha1: str | None
    revision: Revision | None


def _crc(data: bytes) -> str:
    return f"{zlib.crc32(data):08x}"


def _candidates(data: bytes) -> list[int]:
    bases = [0, INES_HEADER] if data.startswith(INES_MAGIC) else [0]
    return [
        offset for base in bases for offset in range(base, len(data) - BIOS_SIZE + 1, BIOS_SIZE)
    ]


def _window(data: bytes, offset: int) -> bytes:
    return data[offset : offset + BIOS_SIZE]


def identify_bios(data: bytes) -> BiosReport:
    exact = len(data) == BIOS_SIZE
    for offset in _candidates(data):
        window = _window(data, offset)
        crc = _crc(window)
        revision = KNOWN_REVISIONS.get(crc) or KNOWN_VARIANTS.get(crc)
        if revision is not None:
            return BiosReport(
                size=len(data),
                exact_size=exact,
                offset=offset,
                crc32=revision.crc32,
                sha1=hashlib.sha1(window, usedforsecurity=False).hexdigest(),
                revision=revision,
            )

    if exact:
        return BiosReport(
            size=len(data),
            exact_size=True,
            offset=0,
            crc32=_crc(data),
            sha1=hashlib.sha1(data, usedforsecurity=False).hexdigest(),
            revision=None,
        )
    return BiosReport(
        size=len(data),
        exact_size=False,
        offset=None,
        crc32=None,
        sha1=None,
        revision=None,
    )


def extract_bios(data: bytes) -> bytes:
    report = identify_bios(data)
    if report.revision is None or report.offset is None:
        message = "the file holds no known BIOS revision, so there is nothing safe to extract"
        raise ValueError(message)
    return _window(data, report.offset)


def emulator_notes(revision: Revision | None, *, exact_size: bool) -> dict[str, str]:
    if not exact_size:
        refusal = f"rejects it, it loads only a file of exactly {BIOS_SIZE} bytes"
        return {"mesen2": refusal, "fceux": refusal, "nestopia": refusal}

    nestopia = (
        "accepts it"
        if revision is not None and revision.crc32 in NESTOPIA_KNOWN
        else "loads it with a warning, it only knows Rev 01A and Rev 02"
    )
    return {"mesen2": "accepts it", "fceux": "accepts it", "nestopia": nestopia}
