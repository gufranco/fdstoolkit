from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from typing import Final

from fdstk.codecs.fds import HEADER_SIZE, has_header

NEAR_THRESHOLD: Final = 0.02
MAX_RUNS: Final = 16
IMAGE_SUFFIXES: Final[frozenset[str]] = frozenset({".fds", ".qd"})


@dataclass(frozen=True, slots=True)
class ByteDiff:
    sizes: tuple[int, int]
    differing_bytes: int
    first_offset: int | None
    last_offset: int | None
    runs: tuple[tuple[int, int], ...]
    truncated_runs: bool

    @property
    def ratio(self) -> float:
        span = max(self.sizes)
        return self.differing_bytes / span if span else 0.0


@dataclass(frozen=True, slots=True)
class NearMatch:
    path: Path
    diff: ByteDiff

    @property
    def near(self) -> bool:
        return self.diff.differing_bytes > 0 and self.diff.ratio <= NEAR_THRESHOLD


def _body(data: bytes) -> bytes:
    return data[HEADER_SIZE:] if has_header(data) else data


def byte_diff(left: bytes, right: bytes, *, max_runs: int = MAX_RUNS) -> ByteDiff:
    one, other = _body(left), _body(right)

    runs: list[tuple[int, int]] = []
    differing = 0
    first: int | None = None
    last: int | None = None
    open_run: int | None = None

    for offset, (before, after) in enumerate(zip_longest(one, other, fillvalue=None)):
        if before == after:
            if open_run is not None:
                runs.append((open_run, offset - open_run))
                open_run = None
            continue
        differing += 1
        first = offset if first is None else first
        last = offset
        if open_run is None:
            open_run = offset

    if open_run is not None:
        runs.append((open_run, max(len(one), len(other)) - open_run))

    return ByteDiff(
        sizes=(len(one), len(other)),
        differing_bytes=differing,
        first_offset=first,
        last_offset=last,
        runs=tuple(runs[:max_runs]),
        truncated_runs=len(runs) > max_runs,
    )


def reference_images(directory: Path, *, skip: Path | None = None) -> Iterator[Path]:
    if not directory.is_dir():
        return
    resolved = skip.resolve() if skip is not None else None
    for path in sorted(directory.rglob("*")):
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if resolved is not None and path.resolve() == resolved:
            continue
        yield path


def nearest_match(data: bytes, candidates: Iterable[Path]) -> NearMatch | None:
    best: NearMatch | None = None
    for path in candidates:
        try:
            other = path.read_bytes()
        except OSError:
            continue
        match = NearMatch(path=path, diff=byte_diff(data, other))
        if best is None or match.diff.differing_bytes < best.diff.differing_bytes:
            best = match
    return best
