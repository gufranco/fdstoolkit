from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Final

import pytest

from fdstoolkit.build.calibration import LARGEST_FACTORY_SIDE
from fdstoolkit.codecs.raw import encode_block_stream, pack_raw03, unpack_raw03
from fdstoolkit.codecs.write_stream import encode_write_stream, factory_violations
from fdstoolkit.core.blocks import TEST_BLOCK_CODE, TEST_PATTERN
from fdstoolkit.drive.captures import Capture
from fdstoolkit.hardware.ports import BlockRead, DriveStatus
from fdstoolkit.hardware.session import WriteRefusedError
from fdstoolkit.quality.checker import (
    CHECKER_BYTES,
    checker_payloads,
    checker_reading,
    run_checker,
)

TRAILING_GAP: Final = 4000
BROKEN_AT: Final = 1200


class CheckerDrive:
    selects_sides = True

    def __init__(self, *, damage: int | None = None, protected: bool = False) -> None:
        self._payloads: dict[int, tuple[bytes, ...]] = {}
        self._captures: list[Capture] = []
        self._damage = damage
        self._protected = protected
        self.write_count = 0

    @property
    def captures(self) -> tuple[Capture, ...]:
        return tuple(self._captures)

    def status(self) -> DriveStatus:
        return DriveStatus(
            disk_present=True, write_protected=self._protected, battery_ok=True, ready=True
        )

    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        self.write_count += 1
        self._payloads = {**self._payloads, side: tuple(blocks)}

    def read_side(self, side: int) -> Iterator[BlockRead]:
        payloads = self._payloads.get(side, ())
        values = bytearray(unpack_raw03(encode_block_stream(payloads)) + bytes(TRAILING_GAP))
        if self._damage is not None and self.write_count:
            spot = len(values) - TRAILING_GAP - self._damage
            values[spot] = 1 if values[spot] == 0 else 0
        read = len(self._captures) + 1
        self._captures.append(Capture(side=side, read=read, data=pack_raw03(bytes(values))))
        heads = [payload for payload in payloads if payload[0] != TEST_BLOCK_CODE]
        return iter(
            BlockRead(index=index, payload=payload, crc_ok=True, attempts=1)
            for index, payload in enumerate(heads)
        )


def _yes(message: str) -> bool:
    del message
    return True


def test_a_checker_side_is_a_header_and_one_test_block_of_the_pattern() -> None:
    # Arrange
    side = 1

    # Act
    payloads = checker_payloads(side)

    # Assert
    assert [payload[0] for payload in payloads] == [1, 2, TEST_BLOCK_CODE]
    assert payloads[0][0x15] == side
    assert payloads[2][1:] == (TEST_PATTERN * CHECKER_BYTES)[:CHECKER_BYTES]
    assert sum(len(payload) for payload in payloads) <= LARGEST_FACTORY_SIDE


def test_a_checker_side_stays_inside_the_factory_layout() -> None:
    # Arrange
    payloads = checker_payloads(0)

    # Act
    problems = factory_violations(encode_write_stream(payloads))

    # Assert
    assert problems == ()


def test_a_clean_read_of_a_checker_side_matches_every_byte() -> None:
    # Arrange
    values = unpack_raw03(encode_block_stream(checker_payloads(0))) + bytes(TRAILING_GAP)

    # Act
    reading = checker_reading(values)

    # Assert
    assert (reading.matched, reading.expected, reading.verified) == (
        CHECKER_BYTES,
        CHECKER_BYTES,
        True,
    )


def test_a_read_with_no_test_block_matches_nothing() -> None:
    # Arrange
    values = unpack_raw03(encode_block_stream(checker_payloads(0)[:2])) + bytes(TRAILING_GAP)

    # Act
    reading = checker_reading(values)

    # Assert
    assert reading.matched == 0
    assert reading.render() == "no type 5 test block read back"


def test_a_run_writes_the_side_and_reads_the_pattern_back() -> None:
    # Arrange
    drive = CheckerDrive()
    kept: list[bytes] = []

    # Act
    readings = run_checker(drive, sides=1, confirm=_yes, flip=_yes, keep=kept.append)

    # Assert
    assert [reading.verified for reading in readings] == [True]
    assert readings[0].render() == f"side 0: all {CHECKER_BYTES} pattern bytes read back"
    assert len(kept) == 1


def test_a_damaged_read_names_where_the_pattern_broke() -> None:
    # Arrange
    drive = CheckerDrive(damage=BROKEN_AT)

    # Act
    readings = run_checker(drive, sides=1, confirm=_yes, flip=_yes, keep=lambda _: None)

    # Assert
    reading = readings[0]
    assert not reading.verified
    assert reading.render().startswith(
        f"side 0: {reading.matched} of {CHECKER_BYTES} pattern bytes"
    )
    assert reading.matched < CHECKER_BYTES


def test_a_declined_checker_writes_nothing() -> None:
    # Arrange
    drive = CheckerDrive()

    # Act
    with pytest.raises(WriteRefusedError) as raised:
        run_checker(drive, sides=1, confirm=lambda _: False, flip=_yes, keep=lambda _: None)

    # Assert
    assert str(raised.value) == "the operator declined the write"
    assert drive.write_count == 0


def test_a_protected_disk_is_refused_first() -> None:
    # Arrange
    drive = CheckerDrive(protected=True)

    # Act
    with pytest.raises(WriteRefusedError) as raised:
        run_checker(drive, sides=1, confirm=_yes, flip=_yes, keep=lambda _: None)

    # Assert
    assert str(raised.value) == "cannot write: disk is write protected"


def test_two_sides_are_each_written_and_checked() -> None:
    # Arrange
    drive = CheckerDrive()

    # Act
    readings = run_checker(drive, sides=2, confirm=_yes, flip=_yes, keep=lambda _: None)

    # Assert
    assert [reading.side for reading in readings] == [0, 1]
    assert drive.write_count == 2


def test_noise_then_a_block_that_is_not_a_test_block_is_not_taken_for_one() -> None:
    # Arrange
    head = unpack_raw03(encode_block_stream(checker_payloads(0)[:2]))
    noise = bytes([2, 0, 2]) + bytes(600) + bytes([1]) + bytes([3]) * 50
    values = head + noise + bytes(TRAILING_GAP)

    # Act
    reading = checker_reading(values)

    # Assert
    assert reading.found is False
    assert reading.render() == "no type 5 test block read back"
