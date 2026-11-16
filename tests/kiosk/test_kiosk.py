from __future__ import annotations

from datetime import date
from typing import Final

import pytest
from fakes import game_name, seeded

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs import fds
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.edit.diskinfo import apply_edits
from fdstoolkit.edit.kiosk import KIOSK_SERIAL_ENV, KioskError, kiosk_target
from fdstoolkit.identify.provenance import Origin, provenance_of

FAKE = seeded(__name__)
GAME = game_name(FAKE)
IN_RANGE: Final = date(1989, 4, 12)
PAST_RANGE: Final = date(2026, 11, 16)
SERIAL: Final = 0x0123


def _disk(sides: int = 1) -> Disk:
    disk, _ = fds.decode(blank_image(sides=sides, headered=False, formatted=True, game_name=GAME))
    return disk


@pytest.fixture(autouse=True)
def serial(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KIOSK_SERIAL_ENV, "0123")


def test_a_kiosk_rewrite_bumps_the_count_and_stamps_the_date_and_serial() -> None:
    # Arrange
    disk = _disk(sides=2)

    # Act
    stamped = kiosk_target(disk, rewrite_date=None, today=IN_RANGE)

    # Assert
    for side in stamped.sides:
        info = side.disk_info
        assert info is not None
        assert (info.rewrite_count, info.rewritten_date, info.writer_serial) == (
            1,
            (1989, 4, 12),
            SERIAL,
        )


def test_provenance_reads_a_kiosk_rewrite_as_rewritten() -> None:
    # Arrange
    disk = _disk()

    # Act
    stamped = kiosk_target(disk, rewrite_date=None, today=IN_RANGE)

    # Assert
    assert [side.origin for side in provenance_of(stamped).sides] == [Origin.REWRITTEN]


def test_a_second_rewrite_counts_two() -> None:
    # Arrange
    once = kiosk_target(_disk(), rewrite_date=None, today=IN_RANGE)

    # Act
    twice = kiosk_target(once, rewrite_date=None, today=IN_RANGE)

    # Assert
    info = twice.sides[0].disk_info
    assert info is not None
    assert info.rewrite_count == 2


def test_a_date_given_is_stamped_instead_of_today() -> None:
    # Arrange
    disk = _disk()

    # Act
    stamped = kiosk_target(disk, rewrite_date="1990-01-05", today=PAST_RANGE)

    # Assert
    info = stamped.sides[0].disk_info
    assert info is not None
    assert info.rewritten_date == (1990, 1, 5)


def test_a_today_past_what_a_disk_date_holds_asks_for_a_date() -> None:
    # Arrange
    disk = _disk()

    # Act
    with pytest.raises(KioskError) as raised:
        kiosk_target(disk, rewrite_date=None, today=PAST_RANGE)

    # Assert
    assert str(raised.value) == (
        "today, 2026-11-16, is past 2024, the last year a disk date can hold; "
        "pass --rewrite-date with a date a kiosk could have stamped"
    )


def test_a_date_that_is_not_one_is_refused() -> None:
    # Arrange
    disk = _disk()

    # Act
    with pytest.raises(KioskError, match="not a day on the calendar") as raised:
        kiosk_target(disk, rewrite_date="1990-02-30", today=IN_RANGE)

    # Assert
    assert "the rewrite date" in str(raised.value)


def test_no_serial_configured_refuses_before_anything_is_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.delenv(KIOSK_SERIAL_ENV)

    # Act
    with pytest.raises(KioskError) as raised:
        kiosk_target(_disk(), rewrite_date=None, today=IN_RANGE)

    # Assert
    assert str(raised.value).startswith("a kiosk rewrite stamps a Disk Writer serial")
    assert KIOSK_SERIAL_ENV in str(raised.value)


@pytest.mark.parametrize("value", ["xyz", "0000", "FFFF", "10000"])
def test_a_serial_a_kiosk_could_not_carry_is_refused(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    # Arrange
    monkeypatch.setenv(KIOSK_SERIAL_ENV, value)

    # Act
    with pytest.raises(KioskError) as raised:
        kiosk_target(_disk(), rewrite_date=None, today=IN_RANGE)

    # Assert
    assert str(raised.value) == (
        f"{KIOSK_SERIAL_ENV} is {value!r}, and a Disk Writer serial is four hexadecimal "
        "digits from 0001 to FFFE"
    )


def test_a_disk_rewritten_ninety_nine_times_cannot_count_one_more() -> None:
    # Arrange
    disk, _ = apply_edits(_disk(), side=0, edits={"rewrite_count": 99})

    # Act
    with pytest.raises(KioskError) as raised:
        kiosk_target(disk, rewrite_date=None, today=IN_RANGE)

    # Assert
    assert str(raised.value) == "side 0 has been rewritten 99 times, the most its count holds"


def test_a_side_with_no_disk_information_is_left_as_it_is() -> None:
    # Arrange
    empty = Side(blocks=(), tail=b"", capacity=0)
    disk = Disk(sides=(_disk().sides[0], empty))

    # Act
    stamped = kiosk_target(disk, rewrite_date=None, today=IN_RANGE)

    # Assert
    assert stamped.sides[1] == empty


def test_an_unreadable_count_is_taken_as_never_rewritten() -> None:
    # Arrange
    disk = _disk()
    payload = bytearray(disk.sides[0].blocks[0].payload)
    payload[0x34] = 0xFF
    first = Block(kind=BlockKind.DISK_INFO, payload=bytes(payload))
    broken = Disk(sides=(Side(blocks=(first, *disk.sides[0].blocks[1:]), tail=b"", capacity=0),))

    # Act
    stamped = kiosk_target(broken, rewrite_date=None, today=IN_RANGE)

    # Assert
    info = stamped.sides[0].disk_info
    assert info is not None
    assert info.rewrite_count == 1
