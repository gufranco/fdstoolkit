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

UNKNOWN_FIELDS = 4


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


def test_a_media_fault_classifies_as_media() -> None:
    assert (
        HardwareFaultError("unreadable block", kind=FaultKind.MEDIA).error_class is ErrorClass.MEDIA
    )


def test_a_transient_fault_classifies_by_its_message() -> None:
    assert (
        HardwareFaultError("input/output error", kind=FaultKind.TRANSIENT).error_class
        is ErrorClass.MEDIA
    )
    assert HardwareFaultError("odd", kind=FaultKind.TRANSIENT).error_class is ErrorClass.OTHER


def test_a_status_that_knows_nothing_blocks_a_write() -> None:
    status = DriveStatus(
        disk_present=None,
        write_protected=None,
        battery_ok=None,
        ready=None,
    )

    assert not status.can_write
    assert len(status.unknown) == UNKNOWN_FIELDS


def test_an_unknown_status_still_allows_a_read() -> None:
    status = DriveStatus(
        disk_present=None,
        write_protected=None,
        battery_ok=None,
        ready=None,
    )

    assert status.can_read


def test_a_known_absent_disk_blocks_a_read() -> None:
    status = DriveStatus(
        disk_present=False,
        write_protected=None,
        battery_ok=None,
        ready=None,
    )

    assert not status.can_read
    assert "no disk in the drive" in status.blockers


def test_the_write_blockers_name_what_could_not_be_established() -> None:
    status = DriveStatus(
        disk_present=True,
        write_protected=None,
        battery_ok=True,
        ready=True,
    )

    assert not status.can_write
    assert any("write protected is unknown" in reason for reason in status.write_blockers)


def test_the_override_lets_an_unknown_status_write() -> None:
    status = DriveStatus(
        disk_present=None,
        write_protected=None,
        battery_ok=None,
        ready=None,
        assume_writable=True,
    )

    assert status.can_write
    assert status.write_blockers == ()


def test_the_override_does_not_silence_a_known_fault() -> None:
    status = DriveStatus(
        disk_present=True,
        write_protected=True,
        battery_ok=True,
        ready=True,
        assume_writable=True,
    )

    assert not status.can_write
    assert "disk is write protected" in status.write_blockers


def test_a_fully_known_healthy_drive_writes() -> None:
    status = DriveStatus(
        disk_present=True,
        write_protected=False,
        battery_ok=True,
        ready=True,
    )

    assert status.can_write
    assert status.unknown == ()
