from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

from fdstoolkit.identify.dat import Catalogue, DatEntry, load_dat

CACHE_VERSION: Final = 1
FIELDS: Final = ("name", "size", "crc32", "md5", "sha1", "sha256")


def cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "fdstoolkit" / "dat"


def _key(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"v{CACHE_VERSION}-{digest}"


def _as_dict(catalogue: Catalogue) -> dict[str, Any]:
    return {
        "name": catalogue.name,
        "version": catalogue.version,
        "entries": [
            {field: getattr(entry, field) for field in FIELDS} for entry in catalogue.entries
        ],
    }


def _from_dict(payload: dict[str, Any]) -> Catalogue:
    entries: list[dict[str, Any]] = payload["entries"]
    return Catalogue(
        name=str(payload["name"]),
        version=payload["version"],
        entries=tuple(
            DatEntry(
                name=str(entry["name"]),
                size=int(entry["size"]),
                crc32=entry["crc32"],
                md5=entry["md5"],
                sha1=entry["sha1"],
                sha256=entry["sha256"],
            )
            for entry in entries
        ),
    )


class DatCache:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root if root is not None else cache_root()

    @property
    def root(self) -> Path:
        return self._root

    def entries(self) -> Iterator[Path]:
        if not self._root.is_dir():
            return
        yield from sorted(self._root.glob("*.json"))

    def clear(self) -> int:
        paths = list(self.entries())
        for path in paths:
            path.unlink()
        return len(paths)

    def load(self, dat: Path) -> tuple[Catalogue, bool]:
        if not dat.is_file():
            message = f"file not found: {dat}"
            raise ValueError(message)

        target = self._root / f"{_key(dat)}.json"
        cached = self._read(target)
        if cached is not None:
            return cached, True

        catalogue = load_dat(dat)
        self._root.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(_as_dict(catalogue), sort_keys=True), encoding="utf-8")
        return catalogue, False

    def _read(self, target: Path) -> Catalogue | None:
        if not target.is_file():
            return None
        try:
            payload: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
            return _from_dict(payload)
        except (ValueError, KeyError, TypeError):
            return None
