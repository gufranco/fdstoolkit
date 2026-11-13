from __future__ import annotations

from collections.abc import Mapping
from typing import Final, cast

BYTE_LIMIT: Final = 0xFF
NUMBER_BASE: Final = 0


class FieldError(ValueError):
    pass


def mapping(value: object, *, where: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        message = f"{where} is a JSON object, got {type(value).__name__}"
        raise FieldError(message)
    return cast("Mapping[str, object]", value)


def objects(
    entry: Mapping[str, object], key: str, *, where: str
) -> tuple[Mapping[str, object], ...]:
    value = entry.get(key, [])
    if not isinstance(value, list):
        message = f"{where}: {key} is a list, got {type(value).__name__}"
        raise FieldError(message)
    items = cast("list[object]", value)
    return tuple(mapping(item, where=f"{where} {key} {index}") for index, item in enumerate(items))


def required(entry: Mapping[str, object], key: str, *, where: str) -> object:
    if key not in entry:
        message = f"{where} has no {key}"
        raise FieldError(message)
    return entry[key]


def text(entry: Mapping[str, object], key: str, *, where: str, default: str | None = None) -> str:
    value = entry.get(key, default) if default is not None else required(entry, key, where=where)
    if not isinstance(value, str):
        message = f"{where}: {key} is text, got {value!r}"
        raise FieldError(message)
    return value


def number(
    entry: Mapping[str, object],
    key: str,
    *,
    where: str,
    default: int | None = None,
    limit: int = BYTE_LIMIT,
) -> int:
    value = entry.get(key, default) if default is not None else required(entry, key, where=where)
    found = as_int(value, key=key, where=f"{where}: ")
    if not 0 <= found <= limit:
        message = f"{where}: {key} is {found}, and it must be between 0 and {limit}"
        raise FieldError(message)
    return found


def as_int(value: object, *, key: str, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        message = f"{where}{key} is a number, got {value!r}"
        raise FieldError(message)
    if isinstance(value, int):
        return value
    try:
        return int(value, NUMBER_BASE)
    except ValueError as error:
        message = f"{where}{key} {value!r} is not a number; write it as 31 or 0x1F"
        raise FieldError(message) from error
