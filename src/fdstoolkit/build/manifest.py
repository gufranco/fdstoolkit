from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from fdstoolkit.build.blank import GAME_NAME_LENGTH, disk_info_block
from fdstoolkit.codecs.fds import encode
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.core.diskinfo import FIELDS_BY_NAME, SHOWA_EPOCH, VERIFICATION_STRING
from fdstoolkit.edit.files import FileSpec, insert_file

DATE_PATTERN: Final = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
FDS_SIDE_CAPACITY: Final = 65500

LICENCE_LENGTH: Final = len(VERIFICATION_STRING)
LICENCE_NINTENDO: Final = "nintendo"
LICENCE_BYPASS: Final = "bypass"

KINDS: Final[dict[str, FileKind]] = {
    "program": FileKind.PROGRAM,
    "character": FileKind.CHARACTER,
    "nametable": FileKind.NAMETABLE,
}


@dataclass(frozen=True, slots=True)
class ManifestFile:
    name: str
    address: int
    kind: FileKind
    path: Path


@dataclass(frozen=True, slots=True)
class ManifestSide:
    side: int
    disk_number: int
    boot_file: int
    files: tuple[ManifestFile, ...]


@dataclass(frozen=True, slots=True)
class DiskManifest:
    game_name: str
    licensee: int
    game_version: int
    manufacturing_date: tuple[int, int, int] | None
    sides: tuple[ManifestSide, ...]
    verification: bytes = VERIFICATION_STRING

    @property
    def boots_on_stock_hardware(self) -> bool:
        return self.verification == VERIFICATION_STRING

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, root: Path) -> DiskManifest:
        game_name = str(payload.get("game_name", "   "))
        if len(game_name) != GAME_NAME_LENGTH:
            message = f"a game name is exactly three characters, got {len(game_name)}"
            raise ValueError(message)

        raw_sides: list[dict[str, Any]] = list(payload.get("sides") or [])
        if not raw_sides:
            message = "a manifest needs at least one side"
            raise ValueError(message)

        return cls(
            game_name=game_name,
            licensee=int(payload.get("licensee", 0)),
            game_version=int(payload.get("game_version", 0)),
            manufacturing_date=_parse_date(payload.get("manufacturing_date")),
            sides=tuple(_side_from(entry, root=root) for entry in raw_sides),
            verification=_parse_licence(payload.get("licence", payload.get("license"))),
        )


def _parse_licence(value: object) -> bytes:
    if value is None or value == LICENCE_NINTENDO:
        return VERIFICATION_STRING
    if value == LICENCE_BYPASS:
        return bytes(LICENCE_LENGTH)
    text = str(value)
    if len(text) != LICENCE_LENGTH:
        message = (
            f"a licence string is {LICENCE_LENGTH} characters, "
            f'"{LICENCE_NINTENDO}" or "{LICENCE_BYPASS}", got {value!r}'
        )
        raise ValueError(message)
    return text.encode("ascii")


def _parse_date(value: object) -> tuple[int, int, int] | None:
    if value is None:
        return None
    match = DATE_PATTERN.match(str(value))
    if match is None:
        message = f"a date is written YYYY-MM-DD, got {value}"
        raise ValueError(message)
    year, month, day = (int(part) for part in match.groups())
    return (year, month, day)


def _file_from(entry: dict[str, Any], *, root: Path) -> ManifestFile:
    kind_name = str(entry.get("kind", "program")).lower()
    kind = KINDS.get(kind_name)
    if kind is None:
        known = ", ".join(sorted(KINDS))
        message = f"unknown file kind {kind_name}, known kinds are {known}"
        raise ValueError(message)

    address = entry.get("address", 0x6000)
    path = Path(str(entry["path"]))
    return ManifestFile(
        name=str(entry.get("name", "")),
        address=int(str(address), 0) if isinstance(address, str) else int(address),
        kind=kind,
        path=path if path.is_absolute() else root / path,
    )


def _side_from(entry: dict[str, Any], *, root: Path) -> ManifestSide:
    return ManifestSide(
        side=int(entry.get("side", 0)),
        disk_number=int(entry.get("disk_number", 0)),
        boot_file=int(entry.get("boot_file", 0)),
        files=tuple(
            _file_from(item, root=root)
            for item in cast("list[dict[str, Any]]", entry.get("files") or [])
        ),
    )


def load_manifest(path: Path) -> DiskManifest:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return DiskManifest.from_dict(payload, root=path.parent)


def _to_bcd(value: int) -> int:
    return ((value // 10) << 4) | (value % 10)


def _stamp(payload: bytearray, name: str, value: bytes) -> None:
    field = FIELDS_BY_NAME[name]
    payload[field.offset : field.offset + field.length] = value


def _info_for(manifest: DiskManifest, side: ManifestSide) -> bytes:
    payload = bytearray(
        disk_info_block(
            side=side.side,
            disk_number=side.disk_number,
            game_name=manifest.game_name,
        )
    )
    _stamp(payload, "verification", manifest.verification)
    _stamp(payload, "licensee", bytes([manifest.licensee]))
    _stamp(payload, "game_version", bytes([manifest.game_version]))
    _stamp(payload, "boot_file", bytes([side.boot_file]))
    if manifest.manufacturing_date is not None:
        year, month, day = manifest.manufacturing_date
        _stamp(
            payload,
            "manufacturing_date",
            bytes([_to_bcd(year - SHOWA_EPOCH), _to_bcd(month), _to_bcd(day)]),
        )
    return bytes(payload)


def build_from_manifest(manifest: DiskManifest) -> bytes:
    sides: list[Side] = []
    for side in manifest.sides:
        blocks = (
            Block(kind=BlockKind.DISK_INFO, payload=_info_for(manifest, side)),
            Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([BlockKind.FILE_AMOUNT, 0])),
        )
        built = Side(blocks=blocks, tail=b"", capacity=FDS_SIDE_CAPACITY)
        disk = Disk(sides=(built,))
        for entry in side.files:
            if not entry.path.is_file():
                message = f"file not found: {entry.path}"
                raise ValueError(message)
            disk = insert_file(
                disk,
                side=0,
                spec=FileSpec(
                    name=entry.name,
                    address=entry.address,
                    kind=entry.kind,
                    data=entry.path.read_bytes(),
                ),
            )
        sides.append(disk.sides[0])

    data, _ = encode(Disk(sides=tuple(sides)), headered=False)
    return data
