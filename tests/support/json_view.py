from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import cast


class JsonShapeError(AssertionError):
    pass


class Json:
    def __init__(self, value: object) -> None:
        self.value = value

    def _items(self) -> Sequence[object]:
        value = self.value
        if isinstance(value, str | bytes) or not isinstance(value, Sequence):
            message = f"{value!r} is not a JSON list"
            raise JsonShapeError(message)
        return cast("Sequence[object]", value)

    def _fields(self) -> Mapping[str, object]:
        value = self.value
        if not isinstance(value, Mapping):
            message = f"{value!r} is not a JSON object"
            raise JsonShapeError(message)
        return cast("Mapping[str, object]", value)

    def __getitem__(self, key: str | int | slice) -> Json:
        if isinstance(key, str):
            return Json(self._fields()[key])
        return Json(self._items()[key])

    def __eq__(self, other: object) -> bool:
        found = other.value if isinstance(other, Json) else other
        return self.value == found

    def __hash__(self) -> int:
        message = "a JSON view compares by value, so it cannot be hashed"
        raise TypeError(message)

    def __contains__(self, item: object) -> bool:
        if isinstance(self.value, str):
            return isinstance(item, str) and item in self.value
        if isinstance(self.value, Mapping):
            return item in self._fields()
        return item in self._items()

    def __len__(self) -> int:
        if isinstance(self.value, str):
            return len(self.value)
        if isinstance(self.value, Mapping):
            return len(self._fields())
        return len(self._items())

    def __bool__(self) -> bool:
        return bool(self.value)

    def __iter__(self) -> Iterator[Json]:
        return (Json(item) for item in self._items())

    def __str__(self) -> str:
        return str(self.value)

    def __repr__(self) -> str:
        return f"Json({self.value!r})"

    def text(self) -> str:
        if isinstance(self.value, str):
            return self.value
        message = f"{self.value!r} is not JSON text"
        raise JsonShapeError(message)

    def number(self) -> float:
        if isinstance(self.value, int | float) and not isinstance(self.value, bool):
            return self.value
        message = f"{self.value!r} is not a JSON number"
        raise JsonShapeError(message)
