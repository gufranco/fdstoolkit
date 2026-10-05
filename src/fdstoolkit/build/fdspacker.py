from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from functools import cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Final, cast

from fdstoolkit.codecs.fds import SIDE_SIZE, encode
from fdstoolkit.core.blocks import FILE_NAME_SIZE, Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.core.diskinfo import SHOWA_EPOCH, VERIFICATION_STRING, to_bcd

TEXT_ENCODING: Final = "latin-1"
GAME_NAME_SIZE: Final = 3
BYTE_LIMIT: Final = 0xFF
WORD_LIMIT: Final = 0xFFFF
BCD_BYTE_LIMIT: Final = 159
DEFAULT_FILE_NAME: Final = "FILENAME"
DEFAULT_GAME_TYPE: Final = " "
DATE_PATTERN: Final = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:T[\d:.]*)?$")
HEX_PREFIXES: Final = ("0x", "$")

SIDES: Final[Mapping[str, int]] = {"A": 0, "B": 1}
DISK_TYPES: Final[Mapping[str, int]] = {"FMS": 0, "FSC": 1}
COUNTRIES: Final[Mapping[str, int]] = {"Japan": 0x49}
DISK_TYPES_OTHER: Final[Mapping[str, int]] = {
    "YellowDisk": 0x00,
    "PrototypeSample": 0xFE,
    "BlueDisk": 0xFF,
}
FILE_KINDS: Final[Mapping[str, int]] = {"Program": 0, "Character": 1, "NameTable": 2}
LICENSEES_FILE: Final = "licensees.json"
LISTED_NAMES_LIMIT: Final = 8

FIRST_UNKNOWNS: Final[tuple[tuple[str, int], ...]] = (
    ("unknown02", 0xFF),
    ("unknown03", 0xFF),
    ("unknown04", 0xFF),
    ("unknown05", 0xFF),
    ("unknown06", 0xFF),
)
MIDDLE_UNKNOWNS: Final[tuple[tuple[str, int], ...]] = (
    ("unknown07", 0x61),
    ("unknown08", 0x00),
    ("unknown09", 0x00),
    ("unknown10", 0x02),
    ("unknown11", 0x00),
    ("unknown12", 0x00),
    ("unknown13", 0x00),
    ("unknown14", 0x00),
    ("unknown15", 0x00),
)

SIDE_KEYS: Final = frozenset(
    {
        "write_unknown",
        "licensee_code",
        "game_type",
        "game_version",
        "disk_side",
        "disk_type",
        "unknown01",
        *(name for name, _ in FIRST_UNKNOWNS),
        "country_code",
        *(name for name, _ in MIDDLE_UNKNOWNS),
        "rewritten_date",
        "unknown16",
        "unknown17",
        "disk_writer_serial_number",
        "unknown18",
        "disk_rewrite_count",
        "actual_disk_side",
        "disk_type_other",
        "disk_version",
        "file_amount",
    }
)
FILE_KEYS: Final = frozenset(
    {"file_number", "file_indicate_code", "file_name", "file_address", "file_kind", "data"}
)
TOOLKIT_TOP_KEYS: Final = frozenset(
    {"game_name", "licensee", "game_version", "manufacturing_date", "licence", "license"}
)
TOOLKIT_SIDE_KEYS: Final = frozenset({"side"})
TOOLKIT_FILE_KEYS: Final = frozenset({"name", "address", "kind", "path"})


@cache
def licensees() -> Mapping[str, int]:
    text = resources.files("fdstoolkit.data").joinpath(LICENSEES_FILE).read_text(encoding="utf-8")
    table: dict[str, str] = json.loads(text)["licensees"]
    return MappingProxyType({name: int(code, 16) for code, name in table.items()})


class FdsPackerError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _Where:
    side: int
    file: int | None = None

    def __str__(self) -> str:
        if self.file is None:
            return f"side {self.side}"
        return f"side {self.side} file {self.file}"


def _mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    items = cast("list[object]", value)
    return [cast("Mapping[str, object]", item) for item in items if isinstance(item, dict)]


def _text_of(value: object, *, field: str, where: _Where) -> str:
    if isinstance(value, bool) or not isinstance(value, int | str):
        message = f"{where}: {field} is {value!r}, which is neither a number nor text"
        raise FdsPackerError(message)
    return str(value)


def _parse_number(text: str, *, field: str, where: _Where) -> int:
    lowered = text.lower()
    try:
        for prefix in HEX_PREFIXES:
            if lowered.startswith(prefix):
                return int(lowered.removeprefix(prefix), 16)
        return int(lowered, 10)
    except ValueError as error:
        message = f"{where}: {field} {text!r} is not a number; write it as $1F, 0x1F or 31"
        raise FdsPackerError(message) from error


def _number(value: object, *, field: str, where: _Where, limit: int = BYTE_LIMIT) -> int:
    number = _parse_number(_text_of(value, field=field, where=where), field=field, where=where)
    if not 0 <= number <= limit:
        message = f"{where}: {field} is {number}, outside 0 to {limit}"
        raise FdsPackerError(message)
    return number


def _named(value: object, *, field: str, where: _Where, names: Mapping[str, int]) -> int:
    text = _text_of(value, field=field, where=where)
    by_lower = {key.lower(): number for key, number in names.items()}
    if text.lower() in by_lower:
        return by_lower[text.lower()]
    if text[:1].isdigit() or text.lower().startswith(HEX_PREFIXES):
        return _number(text, field=field, where=where)
    if len(names) > LISTED_NAMES_LIMIT:
        message = (
            f"{where}: {field} {text!r} is neither a number nor a name FDSPacker knows; "
            "write the code in hex, such as $01"
        )
        raise FdsPackerError(message)
    known = ", ".join(names)
    message = f"{where}: {field} {text!r} is not a known name; known names are {known}"
    raise FdsPackerError(message)


def _latin(value: str, *, field: str, where: _Where, size: int) -> bytes:
    if len(value) > size:
        message = f"{where}: {field} {value!r} is longer than {size} characters"
        raise FdsPackerError(message)
    try:
        encoded = value.encode(TEXT_ENCODING)
    except UnicodeEncodeError as error:
        message = f"{where}: {field} {value!r} holds a character outside Latin-1"
        raise FdsPackerError(message) from error
    return encoded.ljust(size, b"\0")


def _game_type(value: object, *, where: _Where) -> int:
    text = _text_of(value, field="game_type", where=where)
    if len(text) == 1:
        return _latin(text, field="game_type", where=where, size=1)[0]
    return _number(text, field="game_type", where=where)


def _date(value: object, *, field: str, where: _Where) -> bytes:
    if value is None:
        return bytes(3)
    text = str(value)
    match = DATE_PATTERN.match(text)
    if match is None:
        message = f"{where}: {field} {text!r} is not a date; write it as YYYY-MM-DD"
        raise FdsPackerError(message)
    year, month, day = (int(part) for part in match.groups())
    shown = f"{year:04}-{month:02}-{day:02}"
    try:
        date(year, month, day)
    except ValueError as error:
        message = f"{where}: {field} {shown} is not a day on the calendar"
        raise FdsPackerError(message) from error
    count = year - SHOWA_EPOCH
    if not 0 <= count <= BCD_BYTE_LIMIT:
        message = f"{where}: {field} {shown} is outside what a Showa year count can hold"
        raise FdsPackerError(message)
    return bytes([to_bcd(count), to_bcd(month), to_bcd(day)])


def _check_keys(
    entry: Mapping[str, object], *, foreign: frozenset[str], where: _Where | str
) -> None:
    mixed = sorted(foreign & entry.keys())
    if mixed:
        message = (
            f"{where} mixes the toolkit's manifest keys ({', '.join(mixed)}) "
            "into an FDSPacker manifest; write one schema or the other"
        )
        raise FdsPackerError(message)


@dataclass(frozen=True, slots=True)
class _PackedFile:
    header: bytes
    data: bytes


@dataclass(frozen=True, slots=True)
class _PackedSide:
    info: bytes
    file_amount: int
    files: tuple[_PackedFile, ...]


def _file_name(entry: Mapping[str, object], *, where: _Where) -> bytes:
    name = entry.get("file_name", DEFAULT_FILE_NAME)
    if not isinstance(name, str):
        message = f"{where}: file_name is {name!r}; a file name is text"
        raise FdsPackerError(message)
    return _latin(name, field="file_name", where=where, size=FILE_NAME_SIZE)


def _file_data(entry: Mapping[str, object], *, root: Path, where: _Where) -> bytes:
    relative = entry.get("data")
    if not isinstance(relative, str) or not relative:
        message = f"{where} has no data; name the file holding its bytes"
        raise FdsPackerError(message)
    path = root / relative
    if not path.is_file():
        message = f"file not found: {path}"
        raise FdsPackerError(message)
    return path.read_bytes()


def _file_from(entry: Mapping[str, object], *, root: Path, where: _Where) -> _PackedFile:
    _check_keys(entry, foreign=TOOLKIT_FILE_KEYS, where=where)
    data = _file_data(entry, root=root, where=where)
    if len(data) > WORD_LIMIT:
        message = f"{where} holds {len(data)} bytes, beyond the {WORD_LIMIT} a header can state"
        raise FdsPackerError(message)
    header = (
        bytes([BlockKind.FILE_HEADER])
        + bytes([_number(entry.get("file_number", 0), field="file_number", where=where)])
        + bytes(
            [_number(entry.get("file_indicate_code", 0), field="file_indicate_code", where=where)]
        )
        + _file_name(entry, where=where)
        + _number(
            entry.get("file_address", 0), field="file_address", where=where, limit=WORD_LIMIT
        ).to_bytes(2, "little")
        + len(data).to_bytes(2, "little")
        + bytes(
            [_named(entry.get("file_kind", 0), field="file_kind", where=where, names=FILE_KINDS)]
        )
    )
    return _PackedFile(header=header, data=bytes([BlockKind.FILE_DATA]) + data)


def _byte(entry: Mapping[str, object], name: str, default: int, *, where: _Where) -> bytes:
    return bytes([_number(entry.get(name, default), field=name, where=where)])


def _enum(
    entry: Mapping[str, object], name: str, names: Mapping[str, int], *, where: _Where
) -> bytes:
    return bytes([_named(entry.get(name, 0), field=name, where=where, names=names)])


def _game_name(entry: Mapping[str, object], *, where: _Where) -> bytes:
    if "game_name" not in entry:
        message = f"{where} has no game_name; FDSPacker refuses a side without one"
        raise FdsPackerError(message)
    name = entry["game_name"]
    if name is None:
        return bytes(GAME_NAME_SIZE)
    if not isinstance(name, str):
        message = f"{where}: game_name is {name!r}; a game name is text"
        raise FdsPackerError(message)
    return _latin(name, field="game_name", where=where, size=GAME_NAME_SIZE)


def _identity(entry: Mapping[str, object], *, where: _Where) -> bytes:
    return (
        bytes([BlockKind.DISK_INFO])
        + VERIFICATION_STRING
        + _enum(entry, "licensee_code", licensees(), where=where)
        + _game_name(entry, where=where)
        + bytes([_game_type(entry.get("game_type", DEFAULT_GAME_TYPE), where=where)])
        + _byte(entry, "game_version", 0, where=where)
        + _enum(entry, "disk_side", SIDES, where=where)
        + _byte(entry, "disk_number", 0, where=where)
        + _enum(entry, "disk_type", DISK_TYPES, where=where)
        + _byte(entry, "unknown01", 0, where=where)
        + _byte(entry, "boot_file", 0, where=where)
    )


def _provenance(entry: Mapping[str, object], *, where: _Where) -> bytes:
    serial = _number(
        entry.get("disk_writer_serial_number", 0),
        field="disk_writer_serial_number",
        where=where,
        limit=WORD_LIMIT,
    )
    rewrites = _number(
        entry.get("disk_rewrite_count", 0),
        field="disk_rewrite_count",
        where=where,
        limit=BCD_BYTE_LIMIT,
    )
    return (
        _date(entry.get("rewritten_date"), field="rewritten_date", where=where)
        + _byte(entry, "unknown16", 0x00, where=where)
        + _byte(entry, "unknown17", 0x80, where=where)
        + serial.to_bytes(2, "little")
        + _byte(entry, "unknown18", 0x00, where=where)
        + bytes([to_bcd(rewrites)])
        + _enum(entry, "actual_disk_side", SIDES, where=where)
        + _enum(entry, "disk_type_other", DISK_TYPES_OTHER, where=where)
        + _byte(entry, "disk_version", 0, where=where)
    )


def _info(entry: Mapping[str, object], *, where: _Where) -> bytes:
    return (
        _identity(entry, where=where)
        + b"".join(_byte(entry, name, default, where=where) for name, default in FIRST_UNKNOWNS)
        + _date(entry.get("manufacturing_date"), field="manufacturing_date", where=where)
        + _enum(entry, "country_code", COUNTRIES, where=where)
        + b"".join(_byte(entry, name, default, where=where) for name, default in MIDDLE_UNKNOWNS)
        + _provenance(entry, where=where)
    )


def _side_from(entry: Mapping[str, object], *, root: Path, number: int) -> _PackedSide:
    where = _Where(side=number)
    _check_keys(entry, foreign=TOOLKIT_SIDE_KEYS, where=where)
    files = tuple(
        _file_from(item, root=root, where=_Where(side=number, file=index))
        for index, item in enumerate(_mappings(entry.get("files")), start=1)
    )
    return _PackedSide(
        info=_info(entry, where=where),
        file_amount=_number(entry.get("file_amount", 0), field="file_amount", where=where),
        files=files,
    )


def _side_of(packed: _PackedSide, *, number: int) -> Side:
    amount = bytes([BlockKind.FILE_AMOUNT, packed.file_amount])
    blocks = (
        Block(kind=BlockKind.DISK_INFO, payload=packed.info),
        Block(kind=BlockKind.FILE_AMOUNT, payload=amount),
        *(
            block
            for item in packed.files
            for block in (
                Block(kind=BlockKind.FILE_HEADER, payload=item.header),
                Block(kind=BlockKind.FILE_DATA, payload=item.data),
            )
        ),
    )
    content = sum(block.size for block in blocks)
    if content > SIDE_SIZE:
        message = f"side {number} does not fit: it holds {content} bytes against {SIDE_SIZE}"
        raise FdsPackerError(message)
    return Side(blocks=blocks, tail=b"", capacity=SIDE_SIZE)


@dataclass(frozen=True, slots=True)
class FdsPackerManifest:
    sides: tuple[_PackedSide, ...]

    @staticmethod
    def recognises(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        sides = _mappings(cast("Mapping[str, object]", payload).get("sides"))
        files = [item for side in sides for item in _mappings(side.get("files"))]
        return any(SIDE_KEYS & side.keys() for side in sides) or any(
            FILE_KEYS & item.keys() for item in files
        )

    @classmethod
    def parse(cls, payload: Mapping[str, object], *, root: Path) -> FdsPackerManifest:
        _check_keys(payload, foreign=TOOLKIT_TOP_KEYS, where="the manifest")
        sides = _mappings(payload.get("sides"))
        if not sides:
            message = "a manifest needs at least one side"
            raise FdsPackerError(message)
        return cls(
            sides=tuple(
                _side_from(entry, root=root, number=number)
                for number, entry in enumerate(sides, start=1)
            )
        )

    def build(self) -> bytes:
        sides = tuple(
            _side_of(packed, number=number) for number, packed in enumerate(self.sides, start=1)
        )
        data, _ = encode(Disk(sides=sides), headered=False)
        return data
