from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from fdstoolkit.build.fields import located
from fdstoolkit.build.manifest import build_manifest_file
from fdstoolkit.core.archive import ArchiveKind, member_names, read_members
from fdstoolkit.core.disk import SIDE_SIZE, SIDES_PER_DISK

ZIP_MAGIC: Final = b"PK\x03\x04"
MANIFEST_SUFFIX: Final = ".json"
UPLOADED_MANIFEST: Final = "manifest.json"
FILES_PER_SIDE: Final = 255
MAX_MEMBERS: Final = SIDES_PER_DISK * FILES_PER_SIDE + 1
MAX_MANIFEST_BYTES: Final = 1024 * 1024
FOLDER: Final = ArchiveKind(what="the manifest folder", beyond="any file a disk side holds")
WHERE: Final = "the uploaded folder"


class PackagedBuildError(ValueError):
    pass


def _manifest_name(names: tuple[str, ...]) -> str:
    found = [name for name in names if "/" not in name and name.endswith(MANIFEST_SUFFIX)]
    if len(found) != 1:
        message = (
            f"the zip holds {len(found)} JSON manifests at its top level, "
            "and a build reads exactly one"
        )
        raise PackagedBuildError(message)
    return found[0]


def _bounded(names: tuple[str, ...]) -> tuple[str, ...]:
    if len(names) > MAX_MEMBERS:
        message = (
            f"the zip holds {len(names)} files, more than the {MAX_MEMBERS} two sides of a "
            "disk can carry with their manifest"
        )
        raise PackagedBuildError(message)
    return names


def _unzipped(data: bytes, folder: Path) -> Path:
    names = _bounded(member_names(data, FOLDER))
    manifest = _manifest_name(names)
    members = {
        **read_members(
            data, [name for name in names if name != manifest], limit=SIDE_SIZE, kind=FOLDER
        ),
        **read_members(data, [manifest], limit=MAX_MANIFEST_BYTES, kind=FOLDER),
    }
    for name, content in members.items():
        target = located(folder, name, confined=True, where=WHERE)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return folder / manifest


def _unpacked(data: bytes, folder: Path) -> Path:
    if data.startswith(ZIP_MAGIC):
        return _unzipped(data, folder)
    target = folder / UPLOADED_MANIFEST
    target.write_bytes(data)
    return target


def build_packaged(data: bytes) -> bytes:
    with TemporaryDirectory(prefix="fdstoolkit-build-") as directory:
        return build_manifest_file(_unpacked(data, Path(directory)), confined=True)
