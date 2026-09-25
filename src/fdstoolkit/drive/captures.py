from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Protocol, cast, runtime_checkable

from fdstoolkit.core.disk import SIDES_PER_DISK
from fdstoolkit.version import VERSION

MANIFEST: Final = "manifest.json"
FORMAT: Final = "fdstoolkit-captures"
FORMAT_VERSION: Final = 1
MAX_CAPTURE_BYTES: Final = 256 * 1024
MAX_MANIFEST_BYTES: Final = 1024 * 1024
FIELDS: Final = ("file", "side", "read", "sha256")


class BundleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Capture:
    side: int
    read: int
    data: bytes

    @property
    def name(self) -> str:
        return f"side{self.side}.read{self.read:02d}.raw03"


@runtime_checkable
class CaptureSource(Protocol):
    @property
    def captures(self) -> tuple[Capture, ...]: ...


def latest_capture(source: object, side: int) -> bytes | None:
    if not isinstance(source, CaptureSource):
        return None
    return next((c.data for c in reversed(source.captures) if c.side == side), None)


@dataclass(frozen=True, slots=True)
class Bundle:
    captures: tuple[Capture, ...]
    image: str
    created: str

    @property
    def sides(self) -> tuple[int, ...]:
        return tuple(sorted({capture.side for capture in self.captures}))

    def of_side(self, side: int) -> tuple[bytes, ...]:
        return tuple(capture.data for capture in self.captures if capture.side == side)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bundle_files(captures: Sequence[Capture], *, image: str, created: str) -> dict[str, bytes]:
    manifest = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "tool": f"fdstoolkit {VERSION}",
        "created": created,
        "image": image,
        "captures": [
            {
                "file": capture.name,
                "side": capture.side,
                "read": capture.read,
                "size": len(capture.data),
                "sha256": _digest(capture.data),
            }
            for capture in captures
        ],
    }
    files = {capture.name: capture.data for capture in captures}
    return {MANIFEST: json.dumps(manifest, indent=2).encode("utf-8"), **files}


def write_bundle(
    directory: Path, captures: Sequence[Capture], *, image: str, created: str
) -> tuple[Path, ...]:
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, data in bundle_files(captures, image=image, created=created).items():
        target = directory / name
        target.write_bytes(data)
        written.append(target)
    return tuple(written)


def bundle_zip(captures: Sequence[Capture], *, image: str, created: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in bundle_files(captures, image=image, created=created).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _manifest(raw: bytes | None) -> dict[str, object]:
    if raw is None:
        message = f"no {MANIFEST}: this is not a capture bundle that dump --raw wrote"
        raise BundleError(message)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        message = f"{MANIFEST} does not parse: {error}"
        raise BundleError(message) from error
    if not isinstance(parsed, dict):
        message = f"{MANIFEST} is not a capture manifest"
        raise BundleError(message)
    manifest = cast("dict[str, object]", parsed)
    if manifest.get("format") != FORMAT:
        message = f"{MANIFEST} is not a capture manifest"
        raise BundleError(message)
    return manifest


def _entry(entry: dict[str, object]) -> tuple[str, int, int, str]:
    if any(field not in entry for field in FIELDS):
        message = f"an entry in {MANIFEST} does not describe a capture: {entry}"
        raise BundleError(message)
    name, side, read, digest = (entry[field] for field in FIELDS)
    if not isinstance(side, int) or not 0 <= side < SIDES_PER_DISK:
        message = f"{name} names side {side}, and a disk has sides 0 and 1"
        raise BundleError(message)
    return str(name), side, int(str(read)), str(digest)


def _capture(entry: dict[str, object], fetch: Mapping[str, bytes | None]) -> Capture:
    name, side, read, digest = _entry(entry)
    data = fetch.get(name)
    if data is None:
        message = f"{name} is missing from the bundle"
        raise BundleError(message)
    if _digest(data) != digest:
        message = f"{name} does not match its digest, so it changed after it was kept"
        raise BundleError(message)
    return Capture(side=side, read=read, data=data)


def read_files(files: Mapping[str, bytes | None]) -> Bundle:
    raw = files.get(MANIFEST)
    manifest = _manifest(raw)
    return Bundle(
        captures=tuple(_capture(entry, files) for entry in _listed(raw)),
        image=str(manifest.get("image", "")),
        created=str(manifest.get("created", "")),
    )


def _member(archive: zipfile.ZipFile, name: str, limit: int) -> bytes | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > limit:
        message = f"{name} is larger than any capture a drive returns"
        raise BundleError(message)
    return archive.read(info)


def read_zip(data: bytes) -> Bundle:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        message = "the capture bundle is not a zip archive"
        raise BundleError(message) from error
    with archive:
        manifest = _member(archive, MANIFEST, MAX_MANIFEST_BYTES)
        names = [str(entry.get("file", "")) for entry in _listed(manifest)]
        members = {name: _member(archive, name, MAX_CAPTURE_BYTES) for name in names}
    return read_files({MANIFEST: manifest, **members})


def _listed(raw: bytes | None) -> list[dict[str, object]]:
    entries = _manifest(raw).get("captures", [])
    if not isinstance(entries, list):
        message = f"{MANIFEST} does not list its captures"
        raise BundleError(message)
    listed: list[dict[str, object]] = []
    for entry in cast("list[object]", entries):
        if not isinstance(entry, dict):
            message = f"an entry in {MANIFEST} does not describe a capture: {entry}"
            raise BundleError(message)
        listed.append(cast("dict[str, object]", entry))
    return listed


def _directory(directory: Path) -> Bundle:
    manifest_path = directory / MANIFEST
    manifest = manifest_path.read_bytes() if manifest_path.is_file() else None
    names = [str(entry.get("file", "")) for entry in _listed(manifest)]
    members = {
        name: (directory / name).read_bytes() if (directory / name).is_file() else None
        for name in names
    }
    return read_files({MANIFEST: manifest, **members})


def load_bundle(path: Path) -> Bundle:
    if path.is_dir():
        return _directory(path)
    if path.is_file():
        return read_zip(path.read_bytes())
    message = f"{path} is neither a capture directory nor a zip of one"
    raise BundleError(message)


def created_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
