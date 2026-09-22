from __future__ import annotations

import pytest

from fdstk.hardware.ports import (
    BlockRead,
    DriveStatus,
    ErrorClass,
    FaultKind,
    HardwareFaultError,
    classify,
)


def test_a_block_read_carries_its_bytes_and_verdict() -> None:
    read = BlockRead(index=3, payload=bytes([0x02, 0x01]), crc_ok=True, attempts=1)

    assert read.index == 3
    assert read.crc_ok
    assert read.attempts == 1


def test_a_block_read_that_needed_retries_is_marginal() -> None:
    assert not BlockRead(index=0, payload=b"\x04", crc_ok=True, attempts=1).is_marginal
    assert BlockRead(index=0, payload=b"\x04", crc_ok=True, attempts=2).is_marginal


def test_a_block_read_with_a_bad_crc_is_not_marginal_but_failed() -> None:
    read = BlockRead(index=0, payload=b"\x04", crc_ok=False, attempts=3)

    assert read.failed


def test_drive_status_reports_readiness() -> None:
    status = DriveStatus(disk_present=True, write_protected=False, battery_ok=True, ready=True)

    assert status.can_read
    assert status.can_write


def test_a_write_protected_drive_can_read_but_not_write() -> None:
    status = DriveStatus(disk_present=True, write_protected=True, battery_ok=True, ready=True)

    assert status.can_read
    assert not status.can_write


def test_an_empty_drive_can_do_neither() -> None:
    status = DriveStatus(disk_present=False, write_protected=False, battery_ok=True, ready=True)

    assert not status.can_read
    assert not status.can_write


def test_a_flat_battery_blocks_a_write() -> None:
    status = DriveStatus(disk_present=True, write_protected=False, battery_ok=False, ready=True)

    assert not status.can_write
    assert status.blockers == ("battery low",)


def test_blockers_name_every_reason() -> None:
    status = DriveStatus(disk_present=False, write_protected=True, battery_ok=False, ready=False)

    assert status.blockers == (
        "no disk in the drive",
        "disk is write protected",
        "battery low",
        "drive not ready",
    )


def test_a_link_fault_stops_the_run() -> None:
    fault = HardwareFaultError("device stopped answering", kind=FaultKind.LINK)

    assert fault.is_severe
    assert fault.error_class is ErrorClass.LINK


def test_a_media_fault_is_severe_too() -> None:
    assert HardwareFaultError("unreadable block", kind=FaultKind.MEDIA).is_severe


def test_a_transient_fault_is_worth_retrying() -> None:
    fault = HardwareFaultError("short read", kind=FaultKind.TRANSIENT)

    assert not fault.is_severe


def test_classify_maps_a_message_to_a_class() -> None:
    assert classify("device not configured") is ErrorClass.LINK
    assert classify("Input/output error") is ErrorClass.MEDIA
    assert classify("something else entirely") is ErrorClass.OTHER


def test_a_fault_is_an_exception() -> None:
    fault = HardwareFaultError("no answer", kind=FaultKind.LINK)

    with pytest.raises(HardwareFaultError, match="no answer"):
        raise fault
