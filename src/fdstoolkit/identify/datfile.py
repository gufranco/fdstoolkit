from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Final
from xml.etree.ElementTree import Element, SubElement, indent, tostring

from fdstoolkit.identify.hashes import digests_of

DOCTYPE: Final = (
    '<?xml version="1.0"?>\n'
    '<!DOCTYPE datafile PUBLIC "-//Logiqx//DTD ROM Management Datafile//EN" '
    '"http://www.logiqx.com/Dats/datafile.dtd">\n'
)


def _text(parent: Element, tag: str, value: str) -> None:
    SubElement(parent, tag).text = value


def build_dat(
    entries: Sequence[tuple[str, bytes]],
    *,
    name: str,
    version: str,
    description: str | None = None,
    author: str | None = None,
    homepage: str | None = None,
) -> str:
    if not entries:
        message = "a DAT needs at least one entry"
        raise ValueError(message)

    root = Element("datafile")
    header = SubElement(root, "header")
    _text(header, "name", name)
    _text(header, "description", description or name)
    _text(header, "version", version)
    if author is not None:
        _text(header, "author", author)
    if homepage is not None:
        _text(header, "homepage", homepage)

    for filename, data in sorted(entries, key=lambda item: PurePosixPath(item[0]).stem):
        digests = digests_of(data)
        title = PurePosixPath(filename).stem
        game = SubElement(root, "game", {"name": title})
        _text(game, "description", title)
        SubElement(
            game,
            "rom",
            {
                "name": filename,
                "size": str(digests.size),
                "crc": digests.crc32,
                "md5": digests.md5,
                "sha1": digests.sha1,
                "sha256": digests.sha256,
            },
        )

    indent(root, space="  ")
    return DOCTYPE + tostring(root, encoding="unicode") + "\n"
