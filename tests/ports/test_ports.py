from __future__ import annotations

import pytest

from fdstoolkit.hardware.ports import (
    BlockRead,
    DriveStatus,
    ErrorClass,
    FaultKind,
    HardwareFaultError,
    classify,
)


def test_a_block_read_carries_its_bytes_and_verdict() -> None:
    # Arrange
    index = 3
    payload = bytes([0x02, 0x01])
    crc_ok = True
    attempts = 1

    # Act
    read = BlockRead(index=index, payload=payload, crc_ok=crc_ok, attempts=attempts)

    # Assert
    assert read.index == 3
    assert read.crc_ok
    assert read.attempts == 1


def test_a_block_read_that_needed_retries_is_marginal() -> None:
    # Arrange
    attempts = (1, 2)

    # Act
    marginal = [
        BlockRead(index=0, payload=b"\x04", crc_ok=True, attempts=count).is_marginal
        for count in attempts
    ]

    # Assert
    assert marginal == [False, True]


def test_a_block_read_with_a_bad_crc_is_not_marginal_but_failed() -> None:
    # Arrange
    index = 0
    payload = b"\x04"
    crc_ok = False
    attempts = 3

    # Act
    read = BlockRead(index=index, payload=payload, crc_ok=crc_ok, attempts=attempts)

    # Assert
    assert read.failed


def test_drive_status_reports_readiness() -> None:
    # Arrange
    disk_present = True
    write_protected = False
    battery_ok = True
    ready = True

    # Act
    status = DriveStatus(
        disk_present=disk_present,
        write_protected=write_protected,
        battery_ok=battery_ok,
        ready=ready,
    )

    # Assert
    assert status.can_read
    assert status.can_write


def test_a_write_protected_drive_can_read_but_not_write() -> None:
    # Arrange
    disk_present = True
    write_protected = True
    battery_ok = True
    ready = True

    # Act
    status = DriveStatus(
        disk_present=disk_present,
        write_protected=write_protected,
        battery_ok=battery_ok,
        ready=ready,
    )

    # Assert
    assert status.can_read
    assert not status.can_write


def test_an_empty_drive_can_do_neither() -> None:
    # Arrange
    disk_present = False
    write_protected = False
    battery_ok = True
    ready = True

    # Act
    status = DriveStatus(
        disk_present=disk_present,
        write_protected=write_protected,
        battery_ok=battery_ok,
        ready=ready,
    )

    # Assert
    assert not status.can_read
    assert not status.can_write


def test_a_flat_battery_blocks_a_write() -> None:
    # Arrange
    disk_present = True
    write_protected = False
    battery_ok = False
    ready = True

    # Act
    status = DriveStatus(
        disk_present=disk_present,
        write_protected=write_protected,
        battery_ok=battery_ok,
        ready=ready,
    )

    # Assert
    assert not status.can_write
    assert status.blockers == ("battery low",)


def test_blockers_name_every_reason() -> None:
    # Arrange
    disk_present = False
    write_protected = True
    battery_ok = False
    ready = False

    # Act
    status = DriveStatus(
        disk_present=disk_present,
        write_protected=write_protected,
        battery_ok=battery_ok,
        ready=ready,
    )

    # Assert
    assert status.blockers == (
        "no disk in the drive",
        "disk is write protected",
        "battery low",
        "drive not ready",
    )


def test_a_link_fault_stops_the_run() -> None:
    # Arrange
    message = "device stopped answering"

    # Act
    fault = HardwareFaultError(message, kind=FaultKind.LINK)

    # Assert
    assert fault.is_severe
    assert fault.error_class is ErrorClass.LINK


def test_a_media_fault_is_severe_too() -> None:
    # Arrange
    kind = FaultKind.MEDIA

    # Act
    fault = HardwareFaultError("unreadable block", kind=kind)

    # Assert
    assert fault.is_severe


def test_a_transient_fault_is_worth_retrying() -> None:
    # Arrange
    message = "short read"

    # Act
    fault = HardwareFaultError(message, kind=FaultKind.TRANSIENT)

    # Assert
    assert not fault.is_severe


def test_classify_maps_a_message_to_a_class() -> None:
    # Arrange
    message = "device not configured"

    # Act
    result = classify(message)

    # Assert
    assert result is ErrorClass.LINK
    assert classify("Input/output error") is ErrorClass.MEDIA
    assert classify("something else entirely") is ErrorClass.OTHER


def test_a_fault_is_an_exception() -> None:
    # Arrange
    fault = HardwareFaultError("no answer", kind=FaultKind.LINK)

    # Act
    with pytest.raises(HardwareFaultError, match="no answer") as raised:
        raise fault

    # Assert
    assert raised.type is HardwareFaultError


def test_a_media_fault_classifies_as_media() -> None:
    # Arrange
    expected = ErrorClass.MEDIA

    # Act
    result = HardwareFaultError("unreadable block", kind=FaultKind.MEDIA).error_class

    # Assert
    assert result is expected


def test_a_transient_fault_classifies_by_its_message() -> None:
    # Arrange
    expected = ErrorClass.MEDIA

    # Act
    result = HardwareFaultError("input/output error", kind=FaultKind.TRANSIENT).error_class

    # Assert
    assert result is expected
    assert HardwareFaultError("odd", kind=FaultKind.TRANSIENT).error_class is ErrorClass.OTHER


def test_a_status_that_knows_nothing_allows_a_write() -> None:
    # Arrange
    disk_present = None
    write_protected = None
    battery_ok = None
    ready = None

    # Act
    status = DriveStatus(
        disk_present=disk_present,
        write_protected=write_protected,
        battery_ok=battery_ok,
        ready=ready,
    )

    # Assert
    assert status.can_write
    assert status.blockers == ()


def test_an_unknown_status_still_allows_a_read() -> None:
    # Arrange
    disk_present = None
    write_protected = None
    battery_ok = None
    ready = None

    # Act
    status = DriveStatus(
        disk_present=disk_present,
        write_protected=write_protected,
        battery_ok=battery_ok,
        ready=ready,
    )

    # Assert
    assert status.can_read


def test_a_known_absent_disk_blocks_a_read() -> None:
    # Arrange
    disk_present = False
    write_protected = None
    battery_ok = None
    ready = None

    # Act
    status = DriveStatus(
        disk_present=disk_present,
        write_protected=write_protected,
        battery_ok=battery_ok,
        ready=ready,
    )

    # Assert
    assert not status.can_read
    assert "no disk in the drive" in status.blockers


def test_a_known_protected_disk_blocks_a_write() -> None:
    # Arrange
    disk_present = True
    write_protected = True
    battery_ok = True
    ready = True

    # Act
    status = DriveStatus(
        disk_present=disk_present,
        write_protected=write_protected,
        battery_ok=battery_ok,
        ready=ready,
    )

    # Assert
    assert not status.can_write
    assert "disk is write protected" in status.blockers


def test_a_fully_known_healthy_drive_writes() -> None:
    # Arrange
    disk_present = True
    write_protected = False
    battery_ok = True
    ready = True

    # Act
    status = DriveStatus(
        disk_present=disk_present,
        write_protected=write_protected,
        battery_ok=battery_ok,
        ready=ready,
    )

    # Assert
    assert status.can_write
    assert status.blockers == ()
