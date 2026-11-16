from __future__ import annotations

import sys

import pytest
from fdsstick_kit import FakeHidDevice, FakeTransport, read_packets, sample_disk

from fdstoolkit.codecs.raw import encode_raw03
from fdstoolkit.hardware.fdsstick import (
    PRODUCT_ID,
    VENDOR_ID,
    FdsStick,
    HidApiTransport,
    ReportId,
    open_fdsstick,
)
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError


def test_the_device_identity_is_the_documented_one() -> None:
    # Arrange
    documented = (0x16D0, 0x0AAA)

    # Act
    identity = (VENDOR_ID, PRODUCT_ID)

    # Assert
    assert identity == documented


def test_reading_a_side_yields_blocks_with_their_crc_verdict() -> None:
    # Arrange
    disk = sample_disk()
    payload = encode_raw03(disk, side=0)
    transport = FakeTransport({ReportId.DISK_CHUNK: read_packets(payload)})

    # Act
    blocks = list(FdsStick(transport).read_side(0))

    # Assert
    assert [block.payload for block in blocks] == [block.payload for block in disk.sides[0].blocks]
    assert all(block.crc_ok for block in blocks)


def test_the_status_says_what_the_hardware_cannot_report() -> None:
    # Arrange
    device = FdsStick(FakeTransport())

    # Act
    status = device.status()

    # Assert
    assert status.can_read
    assert not device.reports_write_protection


def test_closing_releases_the_transport() -> None:
    # Arrange
    transport = FakeTransport()

    # Act
    FdsStick(transport).close()

    # Assert
    assert transport.closed


def test_the_transport_forwards_a_feature_report() -> None:
    # Arrange
    device = FakeHidDevice()

    # Act
    HidApiTransport(device).send_feature(bytes([0x03, 0x01]))

    # Assert
    assert device.sent == [bytes([0x03, 0x01])]


def test_the_transport_keeps_the_report_id_when_the_backend_returns_it() -> None:
    # Arrange
    expected = 0x11

    # Act
    answer = HidApiTransport(FakeHidDevice()).get_feature(0x11, 8)

    # Assert
    assert answer[0] == expected


def test_the_transport_restores_a_stripped_report_id() -> None:
    # Arrange
    expected = 0x11

    # Act
    answer = HidApiTransport(FakeHidDevice(strip_report_id=True)).get_feature(0x11, 8)

    # Assert
    assert answer[0] == expected


def test_the_transport_forwards_an_output_report() -> None:
    # Arrange
    device = FakeHidDevice()

    # Act
    HidApiTransport(device).write_output(bytes([0x12, 0x00]))

    # Assert
    assert device.written == [bytes([0x12, 0x00])]


def test_the_transport_closes_the_device() -> None:
    # Arrange
    device = FakeHidDevice()

    # Act
    HidApiTransport(device).close()

    # Assert
    assert device.closed


def test_opening_without_hidapi_says_how_to_reinstall(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "hid", None)

    # Act
    with pytest.raises(
        HardwareFaultError, match="brew reinstall gufranco/tap/fdstoolkit"
    ) as raised:
        open_fdsstick()

    # Assert
    assert raised.value.kind is FaultKind.LINK


def test_opening_reports_a_device_that_does_not_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    class RefusingDevice(FakeHidDevice):
        def open(self, vendor_id: int, product_id: int) -> None:
            del vendor_id, product_id
            message = "no such device"
            raise OSError(message)

    class FakeModule:
        def device(self) -> FakeHidDevice:
            return RefusingDevice()

    monkeypatch.setitem(sys.modules, "hid", FakeModule())

    # Act
    with pytest.raises(HardwareFaultError, match="no FDSStick answered") as raised:
        open_fdsstick()

    # Assert
    assert raised.type is HardwareFaultError
