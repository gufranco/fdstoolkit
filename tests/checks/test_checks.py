from __future__ import annotations

from dataclasses import replace
from typing import Final

from fakes import game_name, seeded

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs import fds
from fdstoolkit.core.disk import Disk
from fdstoolkit.hardware.ports import BlockRead
from fdstoolkit.hardware.session import DumpResult, SideDump
from fdstoolkit.history.checks import check_entry, drift_lines, drift_of, drift_payload
from fdstoolkit.history.entries import DriveKey, Stamp, disk_key
from fdstoolkit.history.logbook import Entry, EntryKind

FAKE = seeded(__name__)
GAME = game_name(FAKE)
DRIVE: Final = DriveKey(stick="FDS00042", drive="hvc-022")
CLEAN_CHECK: Final = Entry(
    run="run-1",
    recorded="2026-11-01T10:00:00Z",
    kind=EntryKind.CHECK,
    disk="disk-0123456789abcdef",
    title=GAME,
    stick="FDS00042",
    drive="hvc-022",
    grade="clean",
    weak=(),
)
TODAY: Final = replace(
    CLEAN_CHECK, run="run-2", recorded="2026-11-16T17:00:00Z", weak=((0, 1), (0, 4), (0, 6))
)


def _disk() -> Disk:
    disk, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True, game_name=GAME))
    return disk


def _read(disk: Disk, *, retried: tuple[int, ...] = (), changed: int | None = None) -> DumpResult:
    blocks = tuple(
        BlockRead(
            index=index,
            payload=block.payload + b"\x01" if index == changed else block.payload,
            crc_ok=True,
            attempts=2 if index in retried else 1,
        )
        for index, block in enumerate(disk.sides[0].blocks)
    )
    return DumpResult(sides=(SideDump(index=0, blocks=blocks),))


def test_a_check_entry_names_the_blocks_that_needed_a_retry() -> None:
    # Arrange
    disk = _disk()
    stamp = Stamp(run="run-3", recorded="2026-11-16T17:00:00Z")

    # Act
    entry = check_entry(stamp, _read(disk, retried=(1,)), None, DRIVE)

    # Assert
    key = disk_key(disk)
    assert key is not None
    assert entry.kind is EntryKind.CHECK
    assert (entry.disk, entry.drive, entry.weak) == (key.id, "hvc-022", ((0, 1),))
    assert entry.grade == "marginal"


def test_a_check_against_a_reference_counts_a_block_that_read_different() -> None:
    # Arrange
    disk = _disk()
    stamp = Stamp(run="run-4", recorded="2026-11-16T17:00:00Z")

    # Act
    entry = check_entry(stamp, _read(disk, changed=1), disk, DRIVE)

    # Assert
    assert entry.weak == ((0, 1),)


def test_a_reference_with_fewer_blocks_does_not_count_the_extra_ones() -> None:
    # Arrange
    disk = _disk()
    shorter = Disk(sides=(replace(disk.sides[0], blocks=disk.sides[0].blocks[:1]),))
    stamp = Stamp(run="run-5", recorded="2026-11-16T17:00:00Z")

    # Act
    entry = check_entry(stamp, _read(disk), shorter, DRIVE)

    # Assert
    assert entry.weak == ()


def test_three_blocks_on_retry_after_a_clean_check_is_drift() -> None:
    # Arrange
    earlier = (CLEAN_CHECK,)

    # Act
    found = drift_of(earlier, TODAY)

    # Assert
    assert found.since == CLEAN_CHECK
    assert found.moved == ((0, 1), (0, 4), (0, 6))
    assert drift_lines(found) == (
        (
            "the drive moved since the check of 2026-11-01 10:00: 3 block(s) now weak, "
            "side 0 block 1, side 0 block 4, side 0 block 6"
        ),
    )


def test_only_checks_of_the_same_drive_count_as_the_baseline() -> None:
    # Arrange
    dumped = replace(CLEAN_CHECK, run="dump", kind=EntryKind.DUMP, weak=((0, 1), (0, 4), (0, 6)))
    elsewhere = replace(CLEAN_CHECK, run="other", drive="twin", weak=((0, 1), (0, 4), (0, 6)))

    # Act
    found = drift_of((CLEAN_CHECK, dumped, elsewhere), TODAY)

    # Assert
    assert found.since == CLEAN_CHECK
    assert found.moved == TODAY.weak


def test_a_drive_reading_as_before_says_so() -> None:
    # Arrange
    again = replace(CLEAN_CHECK, run="run-6", recorded="2026-11-02T09:00:00Z")

    # Act
    lines = drift_lines(drift_of((CLEAN_CHECK,), again))

    # Assert
    assert lines == ("the drive reads as it did at the check of 2026-11-01 10:00",)


def test_the_first_check_of_a_drive_has_no_baseline() -> None:
    # Arrange
    earlier: tuple[Entry, ...] = ()

    # Act
    found = drift_of(earlier, TODAY)

    # Assert
    assert found.since is None
    assert found.moved == ()
    assert drift_lines(found) == (
        (
            "first check of drive hvc-022 logged with 3 weak block(s); the next check compares "
            "against it"
        ),
    )


def test_the_payload_answers_the_drift_and_its_baseline() -> None:
    # Arrange
    found = drift_of((CLEAN_CHECK,), TODAY)

    # Act
    payload = drift_payload(found)

    # Assert
    assert payload == {
        "headline": drift_lines(found)[0],
        "ok": False,
        "grade": "clean",
        "weak": [[0, 1], [0, 4], [0, 6]],
        "moved": [[0, 1], [0, 4], [0, 6]],
        "since": "2026-11-01T10:00:00Z",
    }


def test_a_first_check_payload_has_no_baseline() -> None:
    # Arrange
    found = drift_of((), CLEAN_CHECK)

    # Act
    payload = drift_payload(found)

    # Assert
    assert (payload["ok"], payload["since"]) == (True, None)
