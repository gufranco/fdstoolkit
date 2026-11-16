from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import TYPE_CHECKING, Final

from capture_fixture import captures_of, disk_with_a_file
from fakes import game_name, seeded
from hid_double import FakeHid, stick

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs import fds
from fdstoolkit.core.blocks import Block
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.drive.monitor import Calibration, Mode
from fdstoolkit.drive.sampling import SideSample
from fdstoolkit.hardware.ports import BlockRead
from fdstoolkit.hardware.session import DumpResult, Grade, SideDump
from fdstoolkit.history.entries import (
    DEFAULT_DRIVE,
    DRIVE_ENV,
    DriveKey,
    Stamp,
    calibration_entry,
    disk_key,
    drive_key,
    dump_entry,
    grade_entry,
    stamp_now,
)
from fdstoolkit.history.logbook import EntryKind

if TYPE_CHECKING:
    import pytest

FAKE = seeded(__name__)
GAME = game_name(FAKE)
STAMP: Final = Stamp(run="run-1", recorded="2026-11-16T17:00:00Z")
DRIVE: Final = DriveKey(stick="FDS00042", drive="hvc-022")
DAMAGED: Final = 3


def _disk() -> Disk:
    disk, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True, game_name=GAME))
    return disk


def _reads(disk: Disk, *, retried: int | None = None, failed: int | None = None) -> DumpResult:
    blocks = tuple(
        BlockRead(
            index=index,
            payload=block.payload,
            crc_ok=index != failed,
            attempts=2 if index == retried else 1,
        )
        for index, block in enumerate(disk.sides[0].blocks)
    )
    return DumpResult(sides=(SideDump(index=0, blocks=blocks),))


def _calibration(missing: tuple[bool, ...]) -> Calibration:
    sample = SideSample(blocks=missing, short=0, long=0, invalid=0, compared=0, referenced=False)
    return Calibration(mode=Mode.HEAD, samples=(sample, sample))


def test_a_disk_is_known_by_a_digest_of_its_disk_information() -> None:
    # Arrange
    disk = _disk()
    expected = hashlib.sha256(disk.sides[0].blocks[0].payload).hexdigest()[:16]

    # Act
    key = disk_key(disk)

    # Assert
    assert key is not None
    assert key.id == f"disk-{expected}"
    assert key.title == GAME


def test_a_side_with_no_disk_information_has_no_identity() -> None:
    # Arrange
    disk = Disk(sides=(Side(blocks=(), tail=b"", capacity=0),))

    # Act
    key = disk_key(disk)

    # Assert
    assert key is None


def test_a_disk_with_a_blank_name_is_still_named() -> None:
    # Arrange
    disk = _disk()
    info = bytearray(disk.sides[0].blocks[0].payload)
    info[16:19] = b"   "
    blocks = (Block(kind=disk.sides[0].blocks[0].kind, payload=bytes(info), stored_crc=None),)
    renamed = Disk(sides=(replace(disk.sides[0], blocks=blocks + disk.sides[0].blocks[1:]),))

    # Act
    key = disk_key(renamed)

    # Assert
    assert key is not None
    assert key.title == "unnamed disk"


def test_a_dump_entry_names_the_blocks_that_needed_a_re_read_or_never_read() -> None:
    # Arrange
    disk = _disk()
    result = _reads(disk, retried=0, failed=1)

    # Act
    entry = dump_entry(STAMP, result, (), grade=Grade.FAILED, drive=DRIVE)

    # Assert
    assert entry.kind is EntryKind.DUMP
    assert entry.weak == ((0, 0), (0, 1))
    assert entry.grade == "failed"
    assert (entry.stick, entry.drive) == ("FDS00042", "hvc-022")
    assert entry.title == GAME


def test_a_dump_entry_counts_the_weak_blocks_its_captures_show() -> None:
    # Arrange
    disk = disk_with_a_file()
    result = _reads(disk)

    # Act
    entry = dump_entry(
        STAMP, result, captures_of(disk, (None, 10, None)), grade=Grade.CLEAN, drive=DRIVE
    )

    # Assert
    assert entry.weak == ((0, DAMAGED),)


def test_a_dump_whose_disk_information_never_read_is_logged_unidentified() -> None:
    # Arrange
    result = DumpResult(sides=(SideDump(index=0, blocks=()),))

    # Act
    entry = dump_entry(STAMP, result, (), grade=Grade.FAILED, drive=DRIVE)

    # Assert
    assert entry.disk is None
    assert entry.title == "unidentified disk"


def test_a_grade_entry_names_the_blocks_failing_their_checksum() -> None:
    # Arrange
    disk = _disk()
    first = disk.sides[0].blocks[0]
    bad = replace(first, stored_crc=first.computed_crc ^ 1)
    damaged = Disk(sides=(replace(disk.sides[0], blocks=(bad, *disk.sides[0].blocks[1:])),))

    # Act
    entry = grade_entry(STAMP, damaged, Grade.FAILED, ())

    # Assert
    assert entry.kind is EntryKind.GRADE
    assert entry.weak == ((0, 0),)
    assert (entry.stick, entry.drive) == (None, None)


def test_a_grade_entry_adds_the_weak_blocks_of_its_captures() -> None:
    # Arrange
    disk = disk_with_a_file()

    # Act
    entry = grade_entry(STAMP, disk, Grade.MARGINAL, captures_of(disk, (None, 10, None)))

    # Assert
    assert entry.weak == ((0, DAMAGED),)
    assert entry.grade == "marginal"


def test_a_calibration_entry_names_every_block_a_read_missed() -> None:
    # Arrange
    result = _calibration((True, False, True, False))

    # Act
    entry = calibration_entry(STAMP, result, side=1, reference=None, drive=DRIVE)

    # Assert
    assert entry.kind is EntryKind.CALIBRATION
    assert entry.weak == ((1, 1), (1, 3))
    assert entry.grade == "not clean"
    assert entry.disk is None
    assert entry.title == "the disk in the drive"


def test_a_calibration_against_a_reference_is_logged_under_that_disk() -> None:
    # Arrange
    reference = _disk()

    # Act
    entry = calibration_entry(
        STAMP, _calibration((True, True)), side=0, reference=reference, drive=DRIVE
    )

    # Assert
    key = disk_key(reference)
    assert key is not None
    assert entry.disk == key.id
    assert entry.grade == "clean"


def test_the_drive_is_known_by_its_stick_serial_and_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(DRIVE_ENV, "twin")
    hid = FakeHid([stick(serial_number="FDS00042")])

    # Act
    key = drive_key(lambda: hid)

    # Assert
    assert key == DriveKey(stick="FDS00042", drive="twin")


def test_an_unlabelled_drive_with_no_stick_listed_is_still_keyed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.delenv(DRIVE_ENV, raising=False)

    # Act
    key = drive_key(lambda: FakeHid([]))

    # Assert
    assert key == DriveKey(stick=None, drive=DEFAULT_DRIVE)


def test_a_stick_with_no_serial_is_keyed_without_one(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.delenv(DRIVE_ENV, raising=False)

    # Act
    key = drive_key(lambda: FakeHid([stick(serial_number="")]))

    # Assert
    assert key.stick is None


def test_a_machine_without_hidapi_keys_the_drive_by_label_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(DRIVE_ENV, "twin")

    def missing() -> FakeHid:
        raise ImportError

    # Act
    key = drive_key(missing)

    # Assert
    assert key == DriveKey(stick=None, drive="twin")


def test_a_usb_listing_that_fails_keys_the_drive_by_label_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(DRIVE_ENV, "twin")

    class Failing(FakeHid):
        def enumerate(self, vendor_id: int, product_id: int) -> list[dict[str, object]]:
            del vendor_id, product_id
            raise OSError

    # Act
    key = drive_key(lambda: Failing([]))

    # Assert
    assert key == DriveKey(stick=None, drive="twin")


def test_every_stamp_is_its_own_run() -> None:
    # Arrange
    first = stamp_now()

    # Act
    second = stamp_now()

    # Assert
    assert first.run != second.run
    assert second.recorded.endswith("Z")
