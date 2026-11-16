from __future__ import annotations

import hashlib
from pathlib import Path

from fdstoolkit.build.fdspacker import FdsPackerManifest
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.disk import Disk

DEFAULT_INFO = (
    b"\x01*NINTENDO-HVC*\x00SMB\x20\x00\x00\x00\x00\x00\x00"
    + b"\xff" * 5
    + b"\x00\x00\x00\x00\x61\x00\x00\x02"
    + b"\x00" * 5
    + b"\x00\x00\x00\x00\x80\x00\x00\x00\x00\x00\x00\x00"
)


def payload_of(tmp_path: Path, name: str, size: int) -> str:
    data = hashlib.shake_256(name.encode()).digest(size)
    (tmp_path / name).write_bytes(data)
    return name


def packer_file(tmp_path: Path, number: int, **fields: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "file_number": number,
        "file_indicate_code": number,
        "file_name": f"FILE{number}",
        "file_address": "$6000",
        "file_kind": "Program",
        "data": payload_of(tmp_path, f"file{number}.bin", 16 + number),
    }
    return {**entry, **fields}


def packer_side(tmp_path: Path, **fields: object) -> dict[str, object]:
    side: dict[str, object] = {
        "game_name": "SMB",
        "file_amount": 1,
        "files": [packer_file(tmp_path, 0)],
    }
    return {**side, **fields}


def build(tmp_path: Path, *sides: dict[str, object]) -> Disk:
    manifest = FdsPackerManifest.parse({"sides": list(sides)}, root=tmp_path)
    disk, _ = decode(manifest.build())
    return disk


def info_of(disk: Disk, side: int = 0) -> bytes:
    return disk.sides[side].blocks[0].payload
