from __future__ import annotations

import logging
import sys
import threading
from collections import deque
from collections.abc import Iterator

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode as decode_fds
from fdstoolkit.codecs.raw import encode_raw03
from fdstoolkit.hardware import fdsstick as fdsstick_module
from fdstoolkit.hardware.fdsstick import (
    CHUNK_PAYLOAD,
    PRODUCT_ID,
    VENDOR_ID,
    WRITE_PAYLOAD,
    FdsStick,
    HidApiTransport,
    ReportId,
    open_fdsstick,
    prime_hid,
)
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError
from fdstoolkit.hardware.watchdog import UNMEASURED_CEILING_S, StallError


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

    def write_output(self, data: bytes) -> int:
        self.outputs.append(bytes(data))
        return len(data)

    def close(self) -> None:
        self.closed = True


BRIEF = 0.05


class HangingTransport(FakeTransport):
    def __init__(self, gate: threading.Event, *, answers: int) -> None:
        super().__init__({ReportId.DISK_CHUNK: read_packets(bytes(CHUNK_PAYLOAD * 4))})
        self.gate = gate
        self.answers = answers
        self.closed_event = threading.Event()

    def get_feature(self, report_id: int, length: int) -> bytes:
        if self.answers <= 0:
            self.gate.wait()
        self.answers -= 1
        return super().get_feature(report_id, length)

    def write_output(self, data: bytes) -> int:
        if self.answers <= 0:
            self.gate.wait()
        self.answers -= 1
        return super().write_output(data)

    def close(self) -> None:
        super().close()
        self.closed_event.set()


@pytest.fixture(name="gate")
def gate_fixture() -> Iterator[threading.Event]:
    gate = threading.Event()
    yield gate
    gate.set()


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


class ThreadNoting(FakeTransport):
    def __init__(self, responses: dict[int, deque[bytes]] | None = None) -> None:
        super().__init__(responses)
        self.threads: set[int] = set()

    def send_feature(self, data: bytes) -> None:
        self.threads.add(threading.get_ident())
        super().send_feature(data)

    def get_feature(self, report_id: int, length: int) -> bytes:
        self.threads.add(threading.get_ident())
        return super().get_feature(report_id, length)

    def write_output(self, data: bytes) -> int:
        self.threads.add(threading.get_ident())
        return super().write_output(data)


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
