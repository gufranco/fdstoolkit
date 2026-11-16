from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final, cast

from fdstoolkit.core.blocks import Block, BlockKind, FileHeader
from fdstoolkit.core.disk import Side
from fdstoolkit.core.diskinfo import DiskInfo
from fdstoolkit.core.files import file_pairs
from fdstoolkit.drive.rescue import IDENTITY_FIELDS, Identity, identity_of
from fdstoolkit.edit.saves import name_looks_like_a_save

FORMAT: Final = "fdstoolkit-save"
FORMAT_VERSION: Final = 1
NOT_A_BACKUP: Final = "this is not a save backup that disk-save wrote"
NOTHING_WRITTEN: Final = "nothing was written"


class SaveBackupError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SaveBackup:
    identity: Identity
    side: int
    number: int
    name: str
    data: bytes


@dataclass(frozen=True, slots=True)
class _File:
    header_block: int
    header: FileHeader
    data: bytes


def _info(index: int, side: Side) -> DiskInfo:
    info = side.disk_info
    if info is None:
        message = f"side {index} carries no disk information, so its game is unknown"
        raise SaveBackupError(message)
    return info


def _files(side: Side) -> tuple[_File, ...]:
    return tuple(
        _File(
            header_block=index,
            header=FileHeader.parse(header.payload),
            data=b"" if data is None else data.payload[1:],
        )
        for index, header, data in file_pairs(side)
    )


def _chosen(index: int, side: Side, number: int | None) -> _File:
    files = _files(side)
    if number is not None:
        found = next((entry for entry in files if entry.header.number == number), None)
        if found is None:
            message = f"side {index} has no file numbered {number}"
            raise SaveBackupError(message)
        return found
    named = [entry for entry in files if name_looks_like_a_save(entry.header.name)]
    if not named:
        message = (
            f"no file on side {index} has a name that reads like a save; pass --file with its "
            "number, which info --files lists"
        )
        raise SaveBackupError(message)
    if len(named) > 1:
        listed = ", ".join(f"{entry.header.number} {entry.header.name}" for entry in named)
        message = f"side {index} has more than one file named like a save: {listed}"
        raise SaveBackupError(message)
    return named[0]


def backup_of(index: int, side: Side, number: int | None) -> SaveBackup:
    info = _info(index, side)
    chosen = _chosen(index, side, number)
    return SaveBackup(
        identity=identity_of(info),
        side=index,
        number=chosen.header.number,
        name=chosen.header.name,
        data=chosen.data,
    )


def backup_bytes(backup: SaveBackup) -> bytes:
    identity = backup.identity
    values = (identity.licensee, identity.game, identity.version, identity.disk)
    document = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "identity": dict(zip(IDENTITY_FIELDS, values, strict=True)),
        "side": backup.side,
        "number": backup.number,
        "name": backup.name,
        "data": backup.data.hex(),
    }
    return json.dumps(document, indent=2).encode("utf-8")


def _int(fields: dict[str, object], name: str) -> int:
    value = fields.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SaveBackupError(NOT_A_BACKUP)
    return value


def _str(fields: dict[str, object], name: str) -> str:
    value = fields.get(name)
    if not isinstance(value, str):
        raise SaveBackupError(NOT_A_BACKUP)
    return value


def _document(data: bytes) -> dict[str, object]:
    try:
        parsed = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise SaveBackupError(NOT_A_BACKUP) from error
    if not isinstance(parsed, dict):
        raise SaveBackupError(NOT_A_BACKUP)
    fields = cast("dict[str, object]", parsed)
    if fields.get("format") != FORMAT or fields.get("version") != FORMAT_VERSION:
        raise SaveBackupError(NOT_A_BACKUP)
    return fields


def _identity(found: object) -> Identity:
    if not isinstance(found, dict):
        raise SaveBackupError(NOT_A_BACKUP)
    fields = cast("dict[str, object]", found)
    return Identity(
        licensee=_int(fields, "licensee"),
        game=_str(fields, "game"),
        version=_int(fields, "version"),
        disk=_int(fields, "disk"),
    )


def load_backup(data: bytes) -> SaveBackup:
    fields = _document(data)
    try:
        payload = bytes.fromhex(_str(fields, "data"))
    except ValueError as error:
        raise SaveBackupError(NOT_A_BACKUP) from error
    return SaveBackup(
        identity=_identity(fields.get("identity")),
        side=_int(fields, "side"),
        number=_int(fields, "number"),
        name=_str(fields, "name"),
        data=payload,
    )


def _check_disk(info: DiskInfo, backup: SaveBackup) -> None:
    found = identity_of(info)
    if found != backup.identity:
        message = (
            f"the save is from {backup.identity.render()}, and the disk in the drive is "
            f"{found.render()}; {NOTHING_WRITTEN}"
        )
        raise SaveBackupError(message)
    if info.side != backup.side:
        message = (
            f"the disk shows side {info.side} face down, and the save belongs to side "
            f"{backup.side}; turn the disk over"
        )
        raise SaveBackupError(message)


def _target(index: int, side: Side, backup: SaveBackup) -> _File:
    found = next(
        (
            entry
            for entry in _files(side)
            if entry.header.number == backup.number and entry.header.name == backup.name
        ),
        None,
    )
    if found is None:
        message = (
            f"side {index} has no file {backup.number} named {backup.name}, so it is another "
            f"release; {NOTHING_WRITTEN}"
        )
        raise SaveBackupError(message)
    if len(found.data) != len(backup.data):
        message = (
            f"file {backup.number} {backup.name} holds {len(found.data)} bytes on the disk and "
            f"{len(backup.data)} in the save, so it is another release; {NOTHING_WRITTEN}"
        )
        raise SaveBackupError(message)
    return found


def restored(index: int, side: Side, backup: SaveBackup) -> Side:
    _check_disk(_info(index, side), backup)
    target = _target(index, side, backup)
    data_index = target.header_block + 1
    swapped = Block(kind=BlockKind.FILE_DATA, payload=bytes([BlockKind.FILE_DATA]) + backup.data)
    blocks = tuple(
        swapped if position == data_index else block for position, block in enumerate(side.blocks)
    )
    return Side(blocks=blocks, tail=side.tail, capacity=side.capacity)
