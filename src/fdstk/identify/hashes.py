from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass

from fdstk.codecs.fds import HEADER_SIZE, has_header


@dataclass(frozen=True, slots=True)
class Digests:
    size: int
    crc32: str
    md5: str
    sha1: str
    sha256: str
    headerless: Digests | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "size": self.size,
            "crc32": self.crc32,
            "md5": self.md5,
            "sha1": self.sha1,
            "sha256": self.sha256,
        }


def _digests(data: bytes) -> Digests:
    return Digests(
        size=len(data),
        crc32=f"{zlib.crc32(data):08x}",
        md5=hashlib.md5(data, usedforsecurity=False).hexdigest(),
        sha1=hashlib.sha1(data, usedforsecurity=False).hexdigest(),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def digests_of(data: bytes) -> Digests:
    whole = _digests(data)
    if not has_header(data):
        return whole
    return Digests(
        size=whole.size,
        crc32=whole.crc32,
        md5=whole.md5,
        sha1=whole.sha1,
        sha256=whole.sha256,
        headerless=_digests(data[HEADER_SIZE:]),
    )


def side_digests(data: bytes, side_size: int) -> tuple[Digests, ...]:
    body = data[HEADER_SIZE:] if has_header(data) else data
    return tuple(
        _digests(body[start : start + side_size]) for start in range(0, len(body), side_size)
    )
