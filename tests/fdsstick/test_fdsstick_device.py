from __future__ import annotations

import logging
import sys
import threading
from collections import deque

import pytest
from fdsstick_kit import (
    BRIEF,
    FakeHidDevice,
    FakeTransport,
    HangingTransport,
    ThreadNoting,
    read_packets,
    sample_disk,
)

from fdstoolkit.hardware import fdsstick as fdsstick_module
from fdstoolkit.hardware.fdsstick import (
    CHUNK_PAYLOAD,
    PRODUCT_ID,
    VENDOR_ID,
    WRITE_PAYLOAD,
    FdsStick,
    ReportId,
    open_fdsstick,
    prime_hid,
)
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError
from fdstoolkit.hardware.watchdog import UNMEASURED_CEILING_S, StallError


def test_opening_returns_a_usable_device(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    device = FakeHidDevice()

    class FakeModule:
        def device(self) -> FakeHidDevice:
            return device

    monkeypatch.setitem(sys.modules, "hid", FakeModule())
    stick = open_fdsstick()

    # Act
    stick.close()

    # Assert
    assert isinstance(stick, FdsStick)
    assert device.opened == (VENDOR_ID, PRODUCT_ID)


def test_a_second_open_is_refused_while_the_first_holds_the_drive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    class FakeModule:
        def device(self) -> FakeHidDevice:
            return FakeHidDevice()

    monkeypatch.setitem(sys.modules, "hid", FakeModule())
    first = open_fdsstick()

    # Act
    with pytest.raises(HardwareFaultError, match="another fdstoolkit") as raised:
        open_fdsstick()

    # Assert
    first.close()
    assert raised.value.kind is FaultKind.LINK


def test_an_open_that_fails_leaves_the_drive_free(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    class RefusingDevice(FakeHidDevice):
        def open(self, vendor_id: int, product_id: int) -> None:
            del vendor_id, product_id
            message = "no such device"
            raise OSError(message)

    class Refusing:
        def device(self) -> FakeHidDevice:
            return RefusingDevice()

    class Working:
        def device(self) -> FakeHidDevice:
            return FakeHidDevice()

    monkeypatch.setitem(sys.modules, "hid", Refusing())
    with pytest.raises(HardwareFaultError, match="no FDSStick answered"):
        open_fdsstick()
    monkeypatch.setitem(sys.modules, "hid", Working())

    # Act
    stick = open_fdsstick()

    # Assert
    stick.close()
    assert stick.closed_lock


def test_writing_a_side_encodes_the_blocks_it_is_given() -> None:
    # Arrange
    transport = FakeTransport()
    disk = sample_disk()

    # Act
    FdsStick(transport).write_side(0, [block.payload for block in disk.sides[0].blocks])

    # Assert
    assert transport.outputs
    assert {packet[0] for packet in transport.outputs} == {ReportId.DISK_WRITE}


def test_every_side_read_keeps_its_pulse_capture() -> None:
    # Arrange
    body = bytes(CHUNK_PAYLOAD)
    packets = deque(
        [
            bytes([ReportId.DISK_CHUNK, 1]) + body,
            bytes([ReportId.DISK_CHUNK, 2]) + bytes(4),
        ]
    )
    stick = FdsStick(FakeTransport({ReportId.DISK_CHUNK: packets}))

    # Act
    list(stick.read_side(0))

    # Assert
    assert len(stick.captures) == 1


def test_the_stick_reports_every_drive_state_as_unknown() -> None:
    # Arrange
    stick = FdsStick(FakeTransport())

    # Act
    status = stick.status()

    # Assert
    assert status.disk_present is None
    assert status.write_protected is None


def test_the_stick_allows_a_read_it_cannot_vouch_for() -> None:
    # Arrange
    stick = FdsStick(FakeTransport())

    # Act
    status = stick.status()

    # Assert
    assert status.can_read


def test_the_stick_allows_a_write_it_cannot_vouch_for() -> None:
    # Arrange
    stick = FdsStick(FakeTransport())

    # Act
    status = stick.status()

    # Assert
    assert status.can_write


def test_the_stick_reads_one_face_and_says_so() -> None:
    # Arrange
    expected = False

    # Act
    result = FdsStick.selects_sides

    # Assert
    assert result is expected


def test_a_stick_that_stops_answering_mid_read_is_a_stall(gate: threading.Event) -> None:
    # Arrange
    transport = HangingTransport(gate, answers=2)
    stick = FdsStick(transport, ceiling=BRIEF)

    # Act
    with pytest.raises(StallError) as caught:
        list(stick.read_side(0))

    # Assert
    assert caught.type is StallError
    assert caught.value.kind is FaultKind.TIMEOUT
    assert "reading side 0" in str(caught.value)
    assert "half written" not in str(caught.value)
    assert stick.captures == ()
    assert not transport.closed_event.is_set()
    gate.set()
    assert transport.closed_event.wait(1.0)


def test_a_stick_that_stops_accepting_a_write_is_a_stall(gate: threading.Event) -> None:
    # Arrange
    transport = HangingTransport(gate, answers=3)
    stick = FdsStick(transport, ceiling=BRIEF)

    # Act
    with pytest.raises(StallError, match="writing side 1") as caught:
        stick.write_side(1, [block.payload for block in sample_disk().sides[0].blocks])

    # Assert
    assert caught.type is StallError
    assert "half written" in str(caught.value)
    assert not transport.closed_event.is_set()
    gate.set()
    assert transport.closed_event.wait(1.0)


def test_a_side_that_reads_in_time_sets_the_limit_for_the_next() -> None:
    # Arrange
    stick = FdsStick(FakeTransport({ReportId.DISK_CHUNK: read_packets(bytes(CHUNK_PAYLOAD * 2))}))

    # Act
    stick.read_raw_side()

    # Assert
    assert stick.watchdog.measured is not None
    assert stick.watchdog.limit < UNMEASURED_CEILING_S


def test_an_unexpected_failure_while_opening_leaves_the_drive_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    class Broken:
        def device(self) -> FakeHidDevice:
            message = "the hid backend failed"
            raise RuntimeError(message)

    class Working:
        def device(self) -> FakeHidDevice:
            return FakeHidDevice()

    monkeypatch.setitem(sys.modules, "hid", Broken())
    with pytest.raises(RuntimeError, match="the hid backend failed"):
        open_fdsstick()
    monkeypatch.setitem(sys.modules, "hid", Working())

    # Act
    stick = open_fdsstick()

    # Assert
    stick.close()
    assert stick.closed_lock


def test_every_usb_call_of_a_read_runs_on_one_thread() -> None:
    # Arrange
    transport = ThreadNoting({ReportId.DISK_CHUNK: read_packets(bytes(CHUNK_PAYLOAD * 4))})

    # Act
    FdsStick(transport).read_raw_side()

    # Assert
    assert len(transport.threads) == 1


def test_every_usb_call_of_a_write_runs_on_one_thread() -> None:
    # Arrange
    transport = ThreadNoting()

    # Act
    FdsStick(transport).write_raw_side(bytes(WRITE_PAYLOAD * 3))

    # Assert
    assert len(transport.threads) == 1
    assert len(transport.outputs) == 3


def test_priming_starts_hidapi_by_listing_the_stick(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    listed: list[tuple[int, int]] = []

    class FakeModule:
        def device(self) -> FakeHidDevice:
            return FakeHidDevice()

        def enumerate(self, vendor_id: int, product_id: int) -> list[dict[str, object]]:
            listed.append((vendor_id, product_id))
            return []

    monkeypatch.setitem(sys.modules, "hid", FakeModule())

    # Act
    prime_hid()

    # Assert
    assert listed == [(VENDOR_ID, PRODUCT_ID)]


def test_priming_without_hidapi_says_so_and_returns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "hid", None)

    # Act
    with caplog.at_level(logging.INFO, logger=fdsstick_module.__name__):
        prime_hid()

    # Assert
    assert "hidapi is not installed" in caplog.text
