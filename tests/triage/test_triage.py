from __future__ import annotations

from typing import Final

import pytest
from capture_fixture import CREATED, DAMAGED, IMAGE, captures_of, disk_with_a_file

from fdstoolkit.codecs.raw import block_regions, pack_raw03, unpack_raw03
from fdstoolkit.drive.captures import Bundle, Capture
from fdstoolkit.drive.triage import (
    ONE_DISK,
    ZONE_VALUES,
    Culprit,
    triage,
    triage_lines,
    triage_payload,
)

FIRST: Final = "disk-a"
SECOND: Final = "disk-b"
THIRD: Final = "disk-c"


def _bundle(*offsets: int | None) -> Bundle:
    return Bundle(captures=captures_of(disk_with_a_file(), offsets), image=IMAGE, created=CREATED)


def _zone_of_damage() -> int:
    values = unpack_raw03(captures_of(disk_with_a_file(), (None,))[0].data)
    start, _ = block_regions(values)[DAMAGED]
    return start // ZONE_VALUES


def test_one_disk_cannot_separate_drive_from_disk() -> None:
    # Arrange
    bundles = {FIRST: _bundle(None, 10, None)}

    # Act
    with pytest.raises(ValueError, match="one disk") as raised:
        triage(bundles)

    # Assert
    assert str(raised.value) == ONE_DISK


def test_a_position_that_fails_on_every_disk_is_the_drive() -> None:
    # Arrange
    bundles = {name: _bundle(None, 10, None) for name in (FIRST, SECOND, THIRD)}

    # Act
    found = triage(bundles)

    # Assert
    assert [(zone.side, zone.zone, zone.culprit, zone.failing) for zone in found.zones] == [
        (0, _zone_of_damage(), Culprit.DRIVE, (FIRST, SECOND, THIRD))
    ]
    assert found.drive_fails


def test_a_position_that_fails_on_one_disk_is_that_disk() -> None:
    # Arrange
    bundles = {FIRST: _bundle(None, 10, None), SECOND: _bundle(None, None, None)}

    # Act
    found = triage(bundles)

    # Assert
    assert [(zone.culprit, zone.failing) for zone in found.zones] == [(Culprit.DISK, (FIRST,))]
    assert not found.drive_fails


def test_a_position_that_fails_on_some_disks_is_left_open() -> None:
    # Arrange
    bundles = {
        FIRST: _bundle(None, 10, None),
        SECOND: _bundle(None, 10, None),
        THIRD: _bundle(None, None, None),
    }

    # Act
    found = triage(bundles)

    # Assert
    assert [zone.culprit for zone in found.zones] == [Culprit.OPEN]


def test_a_block_failing_its_checksum_in_every_read_counts_as_a_failure() -> None:
    # Arrange
    disk = disk_with_a_file()
    values = bytearray(unpack_raw03(captures_of(disk, (None,))[0].data))
    start, _ = block_regions(bytes(values))[DAMAGED]
    values[start + 50] = 1 if values[start + 50] == 0 else 0
    broken = pack_raw03(bytes(values))
    same = Bundle(
        captures=tuple(Capture(side=0, read=read, data=broken) for read in (1, 2)),
        image=IMAGE,
        created=CREATED,
    )

    # Act
    found = triage({FIRST: same, SECOND: _bundle(None, None)})

    # Assert
    assert [(zone.zone, zone.failing) for zone in found.zones] == [(_zone_of_damage(), (FIRST,))]


def test_disks_with_no_failure_say_so() -> None:
    # Arrange
    bundles = {FIRST: _bundle(None, None), SECOND: _bundle(None, None)}

    # Act
    lines = triage_lines(triage(bundles))

    # Assert
    assert lines == ("2 disks, no position fails on any of them",)


def test_the_lines_name_the_culprit_of_each_position() -> None:
    # Arrange
    zone = _zone_of_damage()
    bundles = {name: _bundle(None, 10, None) for name in (FIRST, SECOND)}

    # Act
    lines = triage_lines(triage(bundles))

    # Assert
    low, high = zone * ZONE_VALUES, (zone + 1) * ZONE_VALUES - 1
    assert lines == (
        "2 disks, 1 position(s) fail on every disk: the drive",
        f"side 0 values {low}-{high}: fails on every disk ({FIRST}, {SECOND}), so it is the drive",
    )


def test_the_lines_name_a_disk_and_an_open_position() -> None:
    # Arrange
    zone = _zone_of_damage()
    low, high = zone * ZONE_VALUES, (zone + 1) * ZONE_VALUES - 1
    alone = {FIRST: _bundle(None, 10, None), SECOND: _bundle(None, None)}
    shared = {
        FIRST: _bundle(None, 10, None),
        SECOND: _bundle(None, 10, None),
        THIRD: _bundle(None, None),
    }

    # Act
    found = (triage_lines(triage(alone)), triage_lines(triage(shared)))

    # Assert
    assert found == (
        (
            "2 disks, no position fails on every disk: the failures belong to the disks",
            f"side 0 values {low}-{high}: fails only on {FIRST}, so it is that disk",
        ),
        (
            "3 disks, no position fails on every disk: the failures belong to the disks",
            (
                f"side 0 values {low}-{high}: fails on 2 of 3 disks ({FIRST}, {SECOND}); "
                "read more disks to tell"
            ),
        ),
    )


def test_the_payload_carries_each_zone_and_its_finding() -> None:
    # Arrange
    zone = _zone_of_damage()
    found = triage({name: _bundle(None, 10, None) for name in (FIRST, SECOND)})

    # Act
    payload = triage_payload(found)

    # Assert
    assert payload == {
        "headline": triage_lines(found)[0],
        "ok": False,
        "disks": [FIRST, SECOND],
        "zones": [
            {
                "side": 0,
                "start": zone * ZONE_VALUES,
                "end": (zone + 1) * ZONE_VALUES - 1,
                "culprit": "drive",
                "failing": [FIRST, SECOND],
                "finding": triage_lines(found)[1],
            }
        ],
    }
