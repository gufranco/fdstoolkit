from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final, cast

import pytest
from capture_fixture import DAMAGED, captures_of, disk_with_a_file

from fdstoolkit.codecs.raw import block_regions, pack_raw03, unpack_raw03
from fdstoolkit.drive.captures import read_zip
from fdstoolkit.drive.track import TRACK_BINS, track_lines, track_of, track_payload

INVALID: Final = 3


def _reads(*offsets: int | None) -> list[bytes]:
    return [capture.data for capture in captures_of(disk_with_a_file(), offsets)]


def test_a_steady_side_shows_every_block_and_no_weak_one() -> None:
    # Arrange
    reads = _reads(None, None, None)

    # Act
    track = track_of(reads, 0)

    # Assert
    regions = block_regions(unpack_raw03(reads[0]))
    assert [(block.start, block.end) for block in track.blocks] == list(regions)
    assert [block.kind for block in track.blocks][:2] == ["disk info", "file amount"]
    assert all(block.weak is None for block in track.blocks)
    assert track.blocks[0].label == "block 0, disk info: steady"
    assert track.reads == len(reads)


def test_a_block_whose_pulses_move_between_reads_is_marked_weak() -> None:
    # Arrange
    reads = _reads(None, 10, None)

    # Act
    track = track_of(reads, 0)

    # Assert
    weak = [block for block in track.blocks if block.weak is not None]
    assert [block.index for block in weak] == [DAMAGED]
    assert weak[0].label == "block 3, file data: 1 pulse(s) differ across 3 read(s), 0 invalid"


def test_the_bins_cover_the_read_and_count_every_class() -> None:
    # Arrange
    values = bytes([0, 1, 2, INVALID]) * 1000

    # Act
    track = track_of([pack_raw03(values)], 1)

    # Assert
    assert len(track.bins) == TRACK_BINS
    assert track.bins[0].start == 0
    assert track.bins[-1].end == len(values)
    assert sum(sum(found.classes) for found in track.bins) == len(values)
    assert sum(found.classes[INVALID] for found in track.bins) == len(values) // 4
    assert track.side == 1


def test_a_read_shorter_than_the_bins_gets_a_bin_per_value() -> None:
    # Arrange
    values = bytes([0, 1, 2])

    # Act
    track = track_of([pack_raw03(values)], 0)

    # Assert
    assert [found.classes for found in track.bins][:3] == [(1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0)]


def test_no_read_of_the_side_is_refused() -> None:
    # Arrange
    reads: list[bytes] = []

    # Act
    with pytest.raises(ValueError, match="hold no read of side 1") as raised:
        track_of(reads, 1)

    # Assert
    assert str(raised.value) == "the captures hold no read of side 1"


def test_the_lines_name_each_block_along_the_side() -> None:
    # Arrange
    track = track_of(_reads(None, 10, None), 0)

    # Act
    lines = track_lines(track)

    # Assert
    first, *rest = lines
    assert first == f"side 0, 3 read(s), {track.length} values, {len(track.blocks)} blocks, 1 weak"
    assert rest[0].startswith("block 0  disk info    ")
    assert rest[0].endswith("steady")
    assert rest[DAMAGED].endswith("1 pulse(s) differ across 3 read(s), 0 invalid")


def test_the_payload_carries_every_bin_and_block() -> None:
    # Arrange
    track = track_of(_reads(None, 10, None), 0)

    # Act
    payload = track_payload(track)

    # Assert
    assert payload["headline"] == track_lines(track)[0]
    assert (payload["side"], payload["reads"], payload["length"]) == (0, 3, track.length)
    bins, blocks = payload["bins"], payload["blocks"]
    assert isinstance(bins, list)
    assert isinstance(blocks, list)
    assert len(cast("list[object]", bins)) == len(track.bins)
    blocks = cast("list[dict[str, object]]", blocks)
    weak = [row for row in blocks if row["weak"]]
    assert weak == [
        {
            "index": DAMAGED,
            "kind": "file data",
            "start": track.blocks[DAMAGED].start,
            "end": track.blocks[DAMAGED].end,
            "weak": True,
            "unstable": 1,
            "invalid": 0,
            "missing": 0,
            "label": track.blocks[DAMAGED].label,
        }
    ]
    assert blocks[0]["unstable"] == 0


def test_the_browser_fixture_still_holds_one_weak_block() -> None:
    # Arrange
    folder = Path("tests/fixtures/captures")
    described = json.loads((folder / "weak-block.json").read_text(encoding="utf-8"))
    data = (folder / "weak-block.zip").read_bytes()

    # Act
    track = track_of(read_zip(data).of_side(0), 0)

    # Assert
    assert hashlib.sha256(data).hexdigest() == described["capture_sha256"]
    assert [block.index for block in track.weak] == [DAMAGED]
