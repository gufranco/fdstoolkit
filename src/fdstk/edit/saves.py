from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from fdstk.core.blocks import Block, BlockKind
from fdstk.core.disk import Disk, Side
from fdstk.edit.files import ExtractedFile, extract_files

SAVE_NAME_MARKERS: Final = ("SAVE", "BACKUP", "USR", "RAM", "BRAM")
MIN_DUMPS: Final = 2


@dataclass(frozen=True, slots=True)
class SaveCandidate:
    side: int
    position: int
    name: str
    size: int
    differing_bytes: int
    name_matches_pattern: bool


@dataclass(frozen=True, slots=True)
class SaveRecipe:
    game_name: str
    game_version: int
    side: int
    position: int
    fill: int


@dataclass(frozen=True, slots=True)
class AppliedRecipe:
    side: int
    position: int
    name: str
    size: int
    fill: int


def name_looks_like_a_save(name: str) -> bool:
    upper = name.upper()
    return any(marker in upper for marker in SAVE_NAME_MARKERS)


def _signature(files: Sequence[ExtractedFile]) -> tuple[tuple[int, int, str, int], ...]:
    return tuple((entry.side, entry.position, entry.name, entry.size) for entry in files)


def _differing(first: bytes, second: bytes) -> int:
    longest = max(len(first), len(second))
    padded_first = first.ljust(longest, b"\0")
    padded_second = second.ljust(longest, b"\0")
    return sum(1 for left, right in zip(padded_first, padded_second, strict=True) if left != right)


def find_save_candidates(disks: Sequence[Disk]) -> tuple[SaveCandidate, ...]:
    if len(disks) < MIN_DUMPS:
        message = f"a save candidate needs at least two dumps, got {len(disks)}"
        raise ValueError(message)

    listings = [extract_files(disk) for disk in disks]
    reference = listings[0]
    if any(_signature(other) != _signature(reference) for other in listings[1:]):
        message = "the dumps do not hold the same files, so they are not the same release"
        raise ValueError(message)

    differing: list[SaveCandidate] = []
    for index, entry in enumerate(reference):
        variants = {listing[index].data for listing in listings}
        if len(variants) == 1:
            continue
        differing.append(
            SaveCandidate(
                side=entry.side,
                position=entry.position,
                name=entry.name,
                size=entry.size,
                differing_bytes=max(
                    _differing(entry.data, listing[index].data) for listing in listings[1:]
                ),
                name_matches_pattern=name_looks_like_a_save(entry.name),
            )
        )

    if len(differing) == len(reference) and len(reference) > 1:
        return ()
    return tuple(differing)


def _matches(disk: Disk, recipe: SaveRecipe) -> bool:
    if not 0 <= recipe.side < disk.side_count:
        return False
    info = disk.sides[recipe.side].disk_info
    if info is None:
        return False
    return info.game_name == recipe.game_name and info.game_version == recipe.game_version


def _fill_file(side: Side, position: int, fill: int) -> tuple[Side, ExtractedFile]:
    seen = -1
    blocks = list(side.blocks)
    for index, block in enumerate(blocks):
        if block.kind is not BlockKind.FILE_HEADER:
            continue
        seen += 1
        if seen != position:
            continue
        data_index = index + 1
        if data_index >= len(blocks) or blocks[data_index].kind is not BlockKind.FILE_DATA:
            break
        payload = blocks[data_index].payload
        blocks[data_index] = Block(
            kind=BlockKind.FILE_DATA,
            payload=bytes([BlockKind.FILE_DATA]) + bytes([fill]) * (len(payload) - 1),
            stored_crc=None,
        )
        replaced = Side(blocks=tuple(blocks), tail=side.tail, capacity=side.capacity)
        entry = next(
            item for item in extract_files(Disk(sides=(replaced,))) if item.position == position
        )
        return replaced, entry

    message = f"there is no file at position {position}"
    raise ValueError(message)


def normalise_saves(
    disk: Disk,
    recipes: Sequence[SaveRecipe],
) -> tuple[Disk, tuple[AppliedRecipe, ...]]:
    sides = list(disk.sides)
    applied: list[AppliedRecipe] = []

    for recipe in recipes:
        if not _matches(disk, recipe):
            continue
        replaced, entry = _fill_file(sides[recipe.side], recipe.position, recipe.fill)
        sides[recipe.side] = replaced
        applied.append(
            AppliedRecipe(
                side=recipe.side,
                position=recipe.position,
                name=entry.name,
                size=entry.size,
                fill=recipe.fill,
            )
        )

    return (
        Disk(sides=tuple(sides), header_side_count=disk.header_side_count),
        tuple(applied),
    )
