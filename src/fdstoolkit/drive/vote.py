from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from fdstoolkit.codecs.raw import block_regions, decode_raw03, unpack_raw03
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Side
from fdstoolkit.drive.align import good_block

MIN_VOTERS: Final = 3
LOOKAHEAD: Final = 8
ROUNDS_PER_BLOCK: Final = MIN_VOTERS
NO_FILE: Final = -1
NOTHING_FOUND: Final = "no read found a single block on this side"

Identity = tuple[int, int]


@dataclass(frozen=True, slots=True)
class Read:
    values: bytes
    blocks: tuple[Block, ...]
    regions: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class VoteResult:
    side: Side
    recovered: tuple[int, ...]
    copied: tuple[int, ...]
    unresolved: tuple[int, ...]
    notes: tuple[str, ...]


def identities(blocks: Sequence[Block]) -> tuple[Identity, ...]:
    number = NO_FILE
    found: list[Identity] = []
    for block in blocks:
        if block.kind is BlockKind.FILE_HEADER and len(block.payload) > 1:
            number = block.payload[1]
        keyed = block.kind in {BlockKind.FILE_HEADER, BlockKind.FILE_DATA}
        found.append((int(block.kind), number if keyed else NO_FILE))
    return tuple(found)


Key = tuple[Identity, int]


def keyed(blocks: Sequence[Block]) -> tuple[Key, ...]:
    seen: Counter[Identity] = Counter()
    keys: list[Key] = []
    for identity in identities(blocks):
        keys.append((identity, seen[identity]))
        seen[identity] += 1
    return tuple(keys)


def parse_read(values: bytes) -> Read:
    side, _ = decode_raw03(values)
    return Read(values=values, blocks=side.blocks, regions=block_regions(values))


def occurrence_of(read: Read, slot: int) -> tuple[Identity, int]:
    keys = identities(read.blocks)
    return keys[slot], keys[:slot].count(keys[slot])


def locate(read: Read, identity: Identity, occurrence: int) -> int | None:
    matches = [index for index, key in enumerate(identities(read.blocks)) if key == identity]
    return matches[occurrence] if occurrence < len(matches) else None


def window_of(read: Read, position: int) -> bytes:
    start, end = read.regions[position]
    return read.values[start:end]


def shared_length(windows: Sequence[bytes]) -> int:
    lengths = sorted((len(window) for window in windows), reverse=True)
    return lengths[len(lengths) // 2] if lengths else 0


def majority(windows: Sequence[bytes]) -> bytes:
    voted = bytearray()
    for position in range(shared_length(windows)):
        seen = [window[position] for window in windows if position < len(window)]
        value, count = Counter(seen).most_common(1)[0]
        voted.append(value if count * 2 > len(seen) else seen[0])
    return bytes(voted)


def _agree(first: bytes, at: int, second: bytes, other_at: int) -> int:
    return sum(
        1
        for step in range(LOOKAHEAD)
        if at + step < len(first)
        and other_at + step < len(second)
        and first[at + step] == second[other_at + step]
    )


def align_to(reference: bytes, other: bytes) -> tuple[int | None, ...]:
    placed, _ = alignment(reference, other)
    return placed


def alignment(reference: bytes, other: bytes) -> tuple[tuple[int | None, ...], int]:
    placed: list[int | None] = []
    here = there = skipped = 0
    for _ in range(len(reference) + len(other)):
        if here >= len(reference):
            continue
        if there >= len(other) or reference[here] == other[there]:
            placed.append(other[there] if there < len(other) else None)
            here, there = here + 1, there + 1
            continue
        swapped = _agree(reference, here + 1, other, there + 1)
        extra = _agree(reference, here, other, there + 1)
        lost = _agree(reference, here + 1, other, there)
        if extra > swapped and extra >= lost:
            there += 1
            skipped += 1
            continue
        if lost > swapped:
            placed.append(None)
            here += 1
            continue
        placed.append(other[there])
        here, there = here + 1, there + 1
    return (*placed, *(None,) * (len(reference) - len(placed))), skipped


def aligned_majority(windows: Sequence[bytes], reference: int) -> bytes:
    base = windows[reference]
    columns = [align_to(base, window) for index, window in enumerate(windows) if index != reference]
    voted = bytearray()
    for position, own in enumerate(base):
        seen = [own, *[value for column in columns if (value := column[position]) is not None]]
        value, count = Counter(seen).most_common(1)[0]
        voted.append(value if count * 2 > len(seen) else own)
    return bytes(voted)


def _splice(working: Read, slot: int, window: bytes) -> Read:
    start, end = working.regions[slot]
    return parse_read(working.values[:start] + window + working.values[end:])


@dataclass(frozen=True, slots=True)
class Repair:
    working: Read
    method: str
    note: str = ""


def _repair(working: Read, slot: int, reads: Sequence[Read]) -> Repair | None:
    identity, occurrence = occurrence_of(working, slot)
    positions = [(read, locate(read, identity, occurrence)) for read in reads]
    found = [(read, position) for read, position in positions if position is not None]
    for read, position in found:
        if good_block(read.blocks[position]):
            return Repair(_splice(working, slot, window_of(read, position)), "copied")
    if len(found) < MIN_VOTERS:
        note = f"block {slot}: {len(found)} read(s) reached it and a vote needs {MIN_VOTERS}"
        return Repair(working, "short", note)
    windows = [window_of(read, pos) for read, pos in found]
    for candidate in (
        majority(windows),
        *(aligned_majority(windows, index) for index in range(len(windows))),
    ):
        voted = _splice(working, slot, candidate)
        if slot < len(voted.blocks) and good_block(voted.blocks[slot]):
            return Repair(voted, "voted")
    return None


def vote_side(captures: Sequence[bytes]) -> VoteResult:
    reads = [parse_read(unpack_raw03(packed)) for packed in captures]
    working = max(reads, key=lambda read: len(read.blocks), default=None)
    if working is None or not working.blocks:
        empty = Side(blocks=(), tail=b"", capacity=0)
        return VoteResult(empty, (), (), (), (NOTHING_FOUND,))
    before = {block.payload for block in working.blocks if good_block(block)}
    methods: dict[bytes, str] = {}
    notes: list[str] = []
    tried: set[int] = set()
    for _ in range(len(working.blocks) * ROUNDS_PER_BLOCK):
        failing = [
            slot
            for slot, block in enumerate(working.blocks)
            if not good_block(block) and slot not in tried
        ]
        if not failing:
            break
        slot = failing[0]
        tried.add(slot)
        repair = _repair(working, slot, reads)
        if repair is None:
            continue
        working = repair.working
        notes.extend([repair.note] if repair.note else [])
        if slot < len(working.blocks) and good_block(working.blocks[slot]):
            methods[working.blocks[slot].payload] = repair.method
    return _result(working, before, methods, notes)


def _result(
    working: Read, before: set[bytes], methods: dict[bytes, str], notes: list[str]
) -> VoteResult:
    blocks = working.blocks
    fresh = [
        index
        for index, block in enumerate(blocks)
        if good_block(block) and block.payload not in before
    ]
    copied = tuple(index for index in fresh if methods.get(blocks[index].payload) == "copied")
    recovered = tuple(index for index in fresh if index not in copied)
    unresolved = tuple(index for index, block in enumerate(blocks) if not good_block(block))
    side = Side(blocks=blocks, tail=b"", capacity=0)
    return VoteResult(side, recovered, copied, unresolved, tuple(notes))
