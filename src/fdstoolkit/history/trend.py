from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from fdstoolkit.history.logbook import Entry

EMPTY: Final = "nothing is logged for this yet"
KIND_WIDTH: Final = 12
GRADE_WIDTH: Final = 10

Pair = tuple[int, int]


@dataclass(frozen=True, slots=True)
class Trend:
    entries: tuple[Entry, ...]
    weakened: tuple[Pair, ...]
    settled: tuple[Pair, ...]
    since: Entry | None


def trend_of(entries: Sequence[Entry]) -> Trend:
    listed = tuple(entries)
    if not listed:
        return Trend(entries=(), weakened=(), settled=(), since=None)
    latest = listed[-1]
    previous = next((entry for entry in reversed(listed[:-1]) if entry.kind is latest.kind), None)
    if previous is None:
        return Trend(entries=listed, weakened=(), settled=(), since=None)
    now, before = set(latest.weak), set(previous.weak)
    return Trend(
        entries=listed,
        weakened=tuple(sorted(now - before)),
        settled=tuple(sorted(before - now)),
        since=previous,
    )


def _when(entry: Entry) -> str:
    return entry.recorded.replace("T", " ")[:16]


def _blocks(pairs: Sequence[Pair]) -> str:
    return ", ".join(f"side {side} block {block}" for side, block in pairs)


def _line(entry: Entry) -> str:
    weak = f"{len(entry.weak)} weak: {_blocks(entry.weak)}" if entry.weak else "no weak block"
    kind = entry.kind.value.ljust(KIND_WIDTH)
    grade = entry.grade.ljust(GRADE_WIDTH)
    return f"{_when(entry)}  {kind} {grade} {entry.title}  {weak}"


def _changes(trend: Trend, since: Entry) -> tuple[str, ...]:
    opening = f"since the {since.kind.value} of {_when(since)}"
    if not trend.weakened and not trend.settled:
        return (f"{opening}, no block changed",)
    weakened = (
        (f"{opening}, {len(trend.weakened)} block(s) weakened: {_blocks(trend.weakened)}",)
        if trend.weakened
        else ()
    )
    settled = (
        (f"{opening}, {len(trend.settled)} block(s) read clean again: {_blocks(trend.settled)}",)
        if trend.settled
        else ()
    )
    return (*weakened, *settled)


def trend_lines(trend: Trend) -> tuple[str, ...]:
    if not trend.entries:
        return (EMPTY,)
    listed = tuple(_line(entry) for entry in trend.entries)
    return listed if trend.since is None else (*listed, *_changes(trend, trend.since))
