from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from fdstoolkit.build.blank import GAME_NAME_LENGTH, disk_info_block
from fdstoolkit.build.fdspacker import FdsPackerManifest
from fdstoolkit.build.fields import mapping, number, objects, text
from fdstoolkit.codecs.fds import encode
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.disk import SIDE_SIZE, Disk, Side
from fdstoolkit.core.diskinfo import FIELDS_BY_NAME, VERIFICATION_STRING
from fdstoolkit.core.showa import encode_date, parse_date
from fdstoolkit.edit.files import DEFAULT_LOAD_ADDRESS, FileSpec, insert_file

WORD_LIMIT: Final = 0xFFFF

LICENCE_LENGTH: Final = len(VERIFICATION_STRING)
LICENCE_NINTENDO: Final = "nintendo"
LICENCE_BYPASS: Final = "bypass"

KINDS: Final[dict[str, FileKind]] = {
    "program": FileKind.PROGRAM,
    "character": FileKind.CHARACTER,
    "nametable": FileKind.NAMETABLE,
}


class ManifestShapeError(ValueError):
    pass


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
    def from_dict(cls, payload: Mapping[str, object], *, root: Path) -> DiskManifest:
        where = "the manifest"
        game_name = text(payload, "game_name", where=where, default="   ")
        if len(game_name) != GAME_NAME_LENGTH:
            message = f"a game name is exactly three characters, got {len(game_name)}"
            raise ManifestShapeError(message)
        raw_sides = objects(payload, "sides", where=where)
        if not raw_sides:
            message = "a manifest needs at least one side"
            raise ManifestShapeError(message)
        return cls(
            game_name=game_name,
            licensee=number(payload, "licensee", where=where, default=0),
            game_version=number(payload, "game_version", where=where, default=0),
            manufacturing_date=_parse_date(payload.get("manufacturing_date")),
            sides=tuple(
                _side_from(entry, root=root, number_of=index)
                for index, entry in enumerate(raw_sides, start=1)
            ),
            verification=_parse_licence(payload.get("licence", payload.get("license"))),
        )


def _parse_licence(value: object) -> bytes:
    if value is None or value == LICENCE_NINTENDO:
        return VERIFICATION_STRING
    if value == LICENCE_BYPASS:
        return bytes(LICENCE_LENGTH)
    text_value = str(value)
    if len(text_value) != LICENCE_LENGTH or not text_value.isascii():
        message = (
            f"a licence string is {LICENCE_LENGTH} characters of ASCII text, "
            f'"{LICENCE_NINTENDO}" or "{LICENCE_BYPASS}", got {value!r}'
        )
        raise ManifestShapeError(message)
    return text_value.encode("ascii")


def _parse_date(value: object) -> tuple[int, int, int] | None:
    if value is None:
        return None
    return parse_date(str(value), field="manufacturing_date")


def _file_from(entry: Mapping[str, object], *, root: Path, where: str) -> ManifestFile:
    kind_name = text(entry, "kind", where=where, default="program").lower()
    kind = KINDS.get(kind_name)
    if kind is None:
        known = ", ".join(sorted(KINDS))
        message = f"unknown file kind {kind_name}, known kinds are {known}"
        raise ManifestShapeError(message)
    path = Path(text(entry, "path", where=where))
    return ManifestFile(
        name=text(entry, "name", where=where, default=""),
        address=number(
            entry, "address", where=where, default=DEFAULT_LOAD_ADDRESS, limit=WORD_LIMIT
        ),
        kind=kind,
        path=path if path.is_absolute() else root / path,
    )


def _side_from(entry: Mapping[str, object], *, root: Path, number_of: int) -> ManifestSide:
    where = f"side {number_of}"
    return ManifestSide(
        side=number(entry, "side", where=where, default=0),
        disk_number=number(entry, "disk_number", where=where, default=0),
        boot_file=number(entry, "boot_file", where=where, default=0),
        files=tuple(
            _file_from(item, root=root, where=f"{where} file {index}")
            for index, item in enumerate(objects(entry, "files", where=where), start=1)
        ),
    )


def load_manifest(path: Path) -> DiskManifest:
    payload = mapping(json.loads(path.read_text(encoding="utf-8")), where=path.name)
    return DiskManifest.from_dict(payload, root=path.parent)


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
        _stamp(payload, "manufacturing_date", encode_date(*manifest.manufacturing_date))
    return bytes(payload)


def build_from_manifest(manifest: DiskManifest) -> bytes:
    sides: list[Side] = []
    for side in manifest.sides:
        blocks = (
            Block(kind=BlockKind.DISK_INFO, payload=_info_for(manifest, side)),
            Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([BlockKind.FILE_AMOUNT, 0])),
        )
        built = Side(blocks=blocks, tail=b"", capacity=SIDE_SIZE)
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


def build_manifest_file(path: Path) -> bytes:
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        message = f"a manifest is a JSON object, and {path.name} holds {type(payload).__name__}"
        raise ManifestShapeError(message)
    fields = cast("dict[str, object]", payload)
    if FdsPackerManifest.recognises(fields):
        return FdsPackerManifest.parse(fields, root=path.parent).build()
    return build_from_manifest(DiskManifest.from_dict(fields, root=path.parent))
