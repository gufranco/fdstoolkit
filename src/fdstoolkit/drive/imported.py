from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from fdstoolkit.codecs.qdc import QdcError, is_qdc, qdc_counts
from fdstoolkit.codecs.raw import pack_raw03
from fdstoolkit.core.disk import SIDES_PER_DISK
from fdstoolkit.drive.captures import (
    MANIFEST,
    Bundle,
    BundleError,
    Capture,
    load_bundle,
    read_zip,
    zip_files,
    zip_names,
)
from fdstoolkit.drive.timing import classes_of

LOOPY_MIN_BYTES: Final = 150_000
LOOPY_MAX_BYTES: Final = 750_000
LOOPY_DATA_RANGE: Final = range(0x30, 0xA0)
LOOPY_STRAY_SHARE: Final = 0.25
COUNT_CEILING: Final = 0xFF
SIDE_LETTER: Final = re.compile(r"-([A-Za-z])\.[^.]*$")
IMPORTED: Final = "imported captures"
MAX_IMPORTED_FILES: Final = 16
MAX_IMPORTED_BYTES: Final = LOOPY_MAX_BYTES
UPLOADED_NAME: Final = "capture.raw"


def _is_loopy(data: bytes) -> bool:
    if not LOOPY_MIN_BYTES < len(data) < LOOPY_MAX_BYTES:
        return False
    strays = sum(1 for count in data if count not in LOOPY_DATA_RANGE)
    return strays < len(data) * LOOPY_STRAY_SHARE


def _counts(name: str, data: bytes) -> bytes:
    if is_qdc(data):
        try:
            return bytes(min(count, COUNT_CEILING) for count in qdc_counts(data))
        except QdcError as error:
            message = f"{name}: {error}"
            raise BundleError(message) from error
    if _is_loopy(data):
        return data
    message = (
        f"{name} is neither a capture bundle, a zip holding {MANIFEST}, nor a QDC RAW file, "
        f"nor an FDSStick .raw timing file of one side, which holds {LOOPY_MIN_BYTES} to "
        f"{LOOPY_MAX_BYTES} pulse counts"
    )
    raise BundleError(message)


def _side(name: str) -> int:
    found = SIDE_LETTER.search(name)
    letter = found.group(1).upper() if found else "A"
    side = ord(letter) - ord("A")
    if side >= SIDES_PER_DISK:
        message = f"{name} names side {letter}, and a disk has sides A and B only"
        raise BundleError(message)
    return side


def imported_bundle(files: Mapping[str, bytes]) -> Bundle:
    if not files:
        message = f"there is no {MANIFEST} and no capture file to import"
        raise BundleError(message)
    ordered = sorted((_side(name), name) for name in files)
    return Bundle(
        captures=tuple(
            Capture(
                side=side,
                read=sum(1 for earlier, _ in ordered[:index] if earlier == side) + 1,
                data=pack_raw03(classes_of(_counts(name, files[name]))),
            )
            for index, (side, name) in enumerate(ordered)
        ),
        image=IMPORTED,
        created="",
    )


def _bounded(names: tuple[str, ...]) -> tuple[str, ...]:
    if len(names) > MAX_IMPORTED_FILES:
        message = (
            f"the set holds {len(names)} files, more files than the {MAX_IMPORTED_FILES} "
            "reads a capture set is read from"
        )
        raise BundleError(message)
    return names


def bundle_from_bytes(data: bytes, name: str = UPLOADED_NAME) -> Bundle:
    if not zipfile.is_zipfile(io.BytesIO(data)):
        return imported_bundle({name: data})
    names = zip_names(data)
    if MANIFEST in names:
        return read_zip(data)
    return imported_bundle(zip_files(data, _bounded(names), limit=MAX_IMPORTED_BYTES))


def _directory(path: Path) -> Bundle:
    if (path / MANIFEST).is_file():
        return load_bundle(path)
    files = _bounded(tuple(sorted(entry.name for entry in path.iterdir() if entry.is_file())))
    oversized = [name for name in files if (path / name).stat().st_size > MAX_IMPORTED_BYTES]
    if oversized:
        message = f"{oversized[0]} is larger than any capture of one side"
        raise BundleError(message)
    return imported_bundle({name: (path / name).read_bytes() for name in files})


def bundle_from_path(path: Path) -> Bundle:
    if path.is_dir():
        return _directory(path)
    if path.is_file():
        return bundle_from_bytes(path.read_bytes(), path.name)
    message = f"{path} is neither a capture directory, a zip of one, nor a capture file"
    raise BundleError(message)
