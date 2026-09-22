from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from fdstoolkit.codecs.fds import SIDE_SIZE

MGD1_SUFFIXES: Final = (".A", ".B", ".C", ".D", ".E", ".F", ".G", ".H")


@dataclass(frozen=True, slots=True)
class SideFile:
    name: str
    data: bytes

    @property
    def suffix(self) -> str:
        dot = self.name.rfind(".")
        return self.name[dot:].upper() if dot >= 0 else ""


def side_suffix_for(index: int) -> str:
    if not 0 <= index < len(MGD1_SUFFIXES):
        message = f"there is no MGD1 suffix for side {index}"
        raise ValueError(message)
    return MGD1_SUFFIXES[index]


def split_into_side_files(data: bytes, *, stem: str) -> tuple[SideFile, ...]:
    files: list[SideFile] = []
    for index, start in enumerate(range(0, len(data), SIDE_SIZE)):
        chunk = data[start : start + SIDE_SIZE]
        files.append(SideFile(name=f"{stem}{side_suffix_for(index)}", data=chunk))
    return tuple(files)


def join_side_files(files: Sequence[SideFile]) -> bytes:
    if not files:
        message = "an image needs at least one side file"
        raise ValueError(message)

    ordered: dict[str, bytes] = {}
    for entry in files:
        if entry.suffix not in MGD1_SUFFIXES:
            message = f"{entry.name} carries no MGD1 side letter"
            raise ValueError(message)
        if entry.suffix in ordered:
            message = f"side {entry.suffix} appears twice"
            raise ValueError(message)
        ordered[entry.suffix] = entry.data

    return b"".join(ordered[suffix] for suffix in MGD1_SUFFIXES if suffix in ordered)
