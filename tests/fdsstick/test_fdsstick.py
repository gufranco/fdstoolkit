from __future__ import annotations

from collections import deque

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode as decode_fds
from fdstoolkit.codecs.raw import encode_raw03
from fdstoolkit.hardware import fdsstick as fdsstick_module
from fdstoolkit.hardware.fdsstick import (
    CHUNK_PAYLOAD,
    PRODUCT_ID,
    VENDOR_ID,
    FdsStick,
    HidApiTransport,
    ReportId,
    open_fdsstick,
)
from fdstoolkit.hardware.ports import HardwareFaultError


class FakeTransport:
    def __init__(self, responses: dict[int, deque[bytes]] | None = None) -> None:
        self.features: list[bytes] = []
        self.outputs: list[bytes] = []
        self.responses = responses or {}
        self.closed = False

    def send_feature(self, data: bytes) -> None:
        self.features.append(bytes(data))

    def get_feature(self, report_id: int, length: int) -> bytes:
        queue = self.responses.get(report_id)
        if queue is None or not queue:
            return bytes([report_id]) + bytes(min(length, 8) - 1)
        return queue.popleft()

    def write_output(self, data: bytes) -> None:
        self.outputs.append(bytes(data))

    def close(self) -> None:
        self.closed = True


def sample_disk():  # noqa: ANN201
    disk, _ = decode_fds(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    return disk


def read_packets(payload: bytes) -> deque[bytes]:
    packets: deque[bytes] = deque()
    sequence = 1
    for start in range(0, len(payload), CHUNK_PAYLOAD):
        chunk = payload[start : start + CHUNK_PAYLOAD]
        packets.append(bytes([ReportId.DISK_CHUNK, sequence]) + chunk)
        sequence = 1 if sequence == 0xFF else sequence + 1
    packets.append(bytes([ReportId.DISK_CHUNK, sequence]))
    return packets


def test_the_device_identity_is_the_documented_one() -> None:
    assert VENDOR_ID == 0x16D0
    assert PRODUCT_ID == 0x0AAA


def test_reading_a_side_yields_blocks_with_their_crc_verdict() -> None:
    disk = sample_disk()
    payload = encode_raw03(disk, side=0)
    transport = FakeTransport({ReportId.DISK_CHUNK: read_packets(payload)})

    blocks = list(FdsStick(transport).read_side(0))

    assert [block.payload for block in blocks] == [block.payload for block in disk.sides[0].blocks]
    assert all(block.crc_ok for block in blocks)


def test_the_status_says_what_the_hardware_cannot_report() -> None:
    device = FdsStick(FakeTransport())

    status = device.status()

    assert status.can_read
    assert not device.reports_write_protection


def test_closing_releases_the_transport() -> None:
    transport = FakeTransport()

    FdsStick(transport).close()

    assert transport.closed


class FakeHidDevice:
    def open(self, vendor_id: int, product_id: int) -> None:
        self.opened = (vendor_id, product_id)

    def __init__(self, *, strip_report_id: bool = False) -> None:
        self.sent: list[bytes] = []
        self.written: list[bytes] = []
        self.closed = False
        self.strip_report_id = strip_report_id

    def send_feature_report(self, data: bytes) -> int:
        self.sent.append(bytes(data))
        return len(data)

    def get_feature_report(self, report_id: int, length: int) -> list[int]:
        body = list(range(min(length, 6)))
        if self.strip_report_id:
            return body
        return [report_id, *body]

    def write(self, data: bytes) -> int:
        self.written.append(bytes(data))
        return len(data)

    def close(self) -> None:
        self.closed = True


def test_the_transport_forwards_a_feature_report() -> None:
    device = FakeHidDevice()

    HidApiTransport(device).send_feature(bytes([0x03, 0x01]))

    assert device.sent == [bytes([0x03, 0x01])]


def test_the_transport_keeps_the_report_id_when_the_backend_returns_it() -> None:
    answer = HidApiTransport(FakeHidDevice()).get_feature(0x11, 8)

    assert answer[0] == 0x11


def test_the_transport_restores_a_stripped_report_id() -> None:
    answer = HidApiTransport(FakeHidDevice(strip_report_id=True)).get_feature(0x11, 8)

    assert answer[0] == 0x11


def test_the_transport_forwards_an_output_report() -> None:
    device = FakeHidDevice()

    HidApiTransport(device).write_output(bytes([0x12, 0x00]))

    assert device.written == [bytes([0x12, 0x00])]


def test_the_transport_closes_the_device() -> None:
    device = FakeHidDevice()

    HidApiTransport(device).close()

    assert device.closed


def test_opening_without_hidapi_explains_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse() -> object:
        message = "no module named hid"
        raise ImportError(message)

    monkeypatch.setattr(fdsstick_module, "_load_hid", refuse)

    with pytest.raises(HardwareFaultError, match="hardware extra"):
        open_fdsstick()


def test_opening_reports_a_device_that_does_not_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    class RefusingDevice(FakeHidDevice):
        def open(self, vendor_id: int, product_id: int) -> None:
            del vendor_id, product_id
            message = "no such device"
            raise OSError(message)

    class FakeModule:
        def device(self) -> FakeHidDevice:
            return RefusingDevice()

    monkeypatch.setattr("fdstoolkit.hardware.fdsstick._load_hid", FakeModule)

    with pytest.raises(HardwareFaultError, match="no FDSStick answered"):
        open_fdsstick()


def test_opening_returns_a_usable_device(monkeypatch: pytest.MonkeyPatch) -> None:
    device = FakeHidDevice()

    class FakeModule:
        def device(self) -> FakeHidDevice:
            return device

    monkeypatch.setattr("fdstoolkit.hardware.fdsstick._load_hid", FakeModule)

    stick = open_fdsstick()

    assert isinstance(stick, FdsStick)
    assert device.opened == (VENDOR_ID, PRODUCT_ID)


def test_writing_a_side_encodes_the_blocks_it_is_given() -> None:
    transport = FakeTransport()
    disk = sample_disk()

    FdsStick(transport).write_side(0, [block.payload for block in disk.sides[0].blocks])

    assert transport.outputs
    assert {packet[0] for packet in transport.outputs} == {ReportId.DISK_WRITE}


def test_every_side_read_keeps_its_pulse_capture() -> None:
    body = bytes(CHUNK_PAYLOAD)
    packets = deque(
        [
            bytes([ReportId.DISK_CHUNK, 1]) + body,
            bytes([ReportId.DISK_CHUNK, 2]) + bytes(4),
        ]
    )
    stick = FdsStick(FakeTransport({ReportId.DISK_CHUNK: packets}))

    list(stick.read_side(0))

    assert len(stick.captures) == 1


def test_the_stick_reports_every_drive_state_as_unknown() -> None:
    stick = FdsStick(FakeTransport())

    status = stick.status()

    assert status.disk_present is None
    assert status.write_protected is None
    assert not status.can_write


def test_the_stick_still_allows_a_read_it_cannot_vouch_for() -> None:
    assert FdsStick(FakeTransport()).status().can_read


def test_the_override_lets_the_stick_write() -> None:
    assert FdsStick(FakeTransport(), assume_writable=True).status().can_write


def test_the_stick_reads_one_face_and_says_so() -> None:
    assert FdsStick.selects_sides is False
