from __future__ import annotations

from collections import deque

import pytest

from fdstoolkit.hardware.fdsstick import (
    CHUNK_PAYLOAD,
    MODE_READ,
    MODE_WRITE,
    PRODUCT_ID,
    RAW_SIDE_LIMIT,
    SEQUENCE_WRAP,
    SETTLED_PACKETS,
    VENDOR_ID,
    WRITE_PAYLOAD,
    FdsStick,
    ReportId,
)
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError

WRITE_REPORT_LENGTH = 0x100
CHUNK_REQUEST_LENGTH = CHUNK_PAYLOAD + 3


class RecordingTransport:
    def __init__(self, replies: dict[int, deque[bytes]] | None = None) -> None:
        self.features: list[bytes] = []
        self.outputs: list[bytes] = []
        self.requested: list[tuple[int, int]] = []
        self._replies = replies or {}

    def send_feature(self, data: bytes) -> None:
        self.features.append(data)

    def get_feature(self, report_id: int, length: int) -> bytes:
        self.requested.append((report_id, length))
        queued = self._replies.get(report_id)
        if queued:
            return queued.popleft()
        return bytes([report_id, 1])

    def write_output(self, data: bytes) -> None:
        self.outputs.append(data)

    def close(self) -> None:
        return None


def chunk(sequence: int, payload: bytes) -> bytes:
    return bytes([ReportId.DISK_CHUNK, sequence]) + payload


def full_then_short() -> deque[bytes]:
    return deque([chunk(1, bytes(CHUNK_PAYLOAD)), chunk(2, bytes(4))])


def test_the_device_is_the_one_both_reference_tools_open() -> None:
    assert (VENDOR_ID, PRODUCT_ID) == (0x16D0, 0x0AAA)


def test_the_report_numbers_are_the_ones_the_device_publishes() -> None:
    assert ReportId.DISK_START == 0x10
    assert ReportId.DISK_CHUNK == 0x11
    assert ReportId.DISK_WRITE == 0x12


def test_the_driver_knows_only_the_reports_that_reach_a_real_drive() -> None:
    assert {int(report) for report in ReportId} == {0x10, 0x11, 0x12}


def test_a_read_starts_with_the_start_report_carrying_the_read_mode() -> None:
    transport = RecordingTransport({ReportId.DISK_CHUNK: full_then_short()})

    FdsStick(transport).read_raw_side()

    assert transport.features[0] == bytes([ReportId.DISK_START, MODE_READ])


def test_a_read_pulls_its_data_from_the_chunk_report() -> None:
    transport = RecordingTransport({ReportId.DISK_CHUNK: full_then_short()})

    FdsStick(transport).read_raw_side()

    assert {report for report, _ in transport.requested} == {ReportId.DISK_CHUNK}


def test_a_chunk_is_asked_for_with_room_for_the_id_and_the_sequence() -> None:
    transport = RecordingTransport({ReportId.DISK_CHUNK: full_then_short()})

    FdsStick(transport).read_raw_side()

    assert transport.requested[0] == (ReportId.DISK_CHUNK, CHUNK_REQUEST_LENGTH)


def test_the_payload_starts_after_the_id_and_the_sequence() -> None:
    body = bytes(range(CHUNK_PAYLOAD))
    transport = RecordingTransport(
        {ReportId.DISK_CHUNK: deque([chunk(1, body), chunk(2, b"\x00")])}
    )

    assert FdsStick(transport).read_raw_side().startswith(body)


def test_a_short_chunk_ends_the_side() -> None:
    transport = RecordingTransport(
        {ReportId.DISK_CHUNK: deque([chunk(1, bytes(CHUNK_PAYLOAD)), chunk(2, bytes(8))])}
    )

    assert len(FdsStick(transport).read_raw_side()) == CHUNK_PAYLOAD + 8


def test_a_sequence_that_skips_is_reported_as_lost_data() -> None:
    transport = RecordingTransport(
        {ReportId.DISK_CHUNK: deque([chunk(1, bytes(CHUNK_PAYLOAD)), chunk(9, bytes(4))])}
    )

    with pytest.raises(HardwareFaultError) as raised:
        FdsStick(transport).read_raw_side()

    assert raised.value.kind is FaultKind.MEDIA


def test_a_reply_too_short_to_carry_a_sequence_is_a_link_fault() -> None:
    transport = RecordingTransport({ReportId.DISK_CHUNK: deque([bytes([ReportId.DISK_CHUNK])])})

    with pytest.raises(HardwareFaultError) as raised:
        FdsStick(transport).read_raw_side()

    assert raised.value.kind is FaultKind.LINK


def test_a_write_starts_with_the_start_report_carrying_the_write_mode() -> None:
    transport = RecordingTransport()

    FdsStick(transport).write_raw_side(bytes(WRITE_PAYLOAD))

    assert transport.features[0] == bytes([ReportId.DISK_START, MODE_WRITE])


def test_a_write_sends_its_data_as_output_reports() -> None:
    transport = RecordingTransport()

    FdsStick(transport).write_raw_side(bytes(WRITE_PAYLOAD * 2))

    assert len(transport.outputs) == 2
    assert {packet[0] for packet in transport.outputs} == {ReportId.DISK_WRITE}


def test_every_write_report_fills_the_whole_frame() -> None:
    transport = RecordingTransport()

    FdsStick(transport).write_raw_side(bytes(10))

    assert [len(packet) for packet in transport.outputs] == [WRITE_REPORT_LENGTH]


def test_a_write_sends_nothing_after_its_data() -> None:
    transport = RecordingTransport()

    FdsStick(transport).write_raw_side(bytes(WRITE_PAYLOAD))

    assert transport.features == [bytes([ReportId.DISK_START, MODE_WRITE])]


FLASH_REPORTS = frozenset({0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09})

EMULATOR_REPORTS = frozenset({0x20, 0x21, 0x22, 0x23})


def sent_by_a_full_session() -> set[int]:
    transport = RecordingTransport({ReportId.DISK_CHUNK: full_then_short()})
    stick = FdsStick(transport)

    stick.read_raw_side()
    stick.write_raw_side(bytes(WRITE_PAYLOAD))

    return {packet[0] for packet in transport.features + transport.outputs}


def test_nothing_on_the_wire_touches_the_flash_reports() -> None:
    assert sent_by_a_full_session().isdisjoint(FLASH_REPORTS)


def test_nothing_on_the_wire_drives_the_disk_emulator() -> None:
    assert sent_by_a_full_session().isdisjoint(EMULATOR_REPORTS)


def test_every_report_sent_is_one_the_driver_declares() -> None:
    assert sent_by_a_full_session() <= {int(report) for report in ReportId}


class RefusingTransport(RecordingTransport):
    def __init__(self, *, accept: int) -> None:
        super().__init__()
        self._accept = accept

    def write_output(self, data: bytes) -> None:
        if len(self.outputs) >= self._accept:
            message = "the device stopped accepting output reports"
            raise OSError(message)
        super().write_output(data)


def test_a_device_that_stops_early_is_a_link_fault() -> None:
    transport = RefusingTransport(accept=3)

    with pytest.raises(HardwareFaultError) as raised:
        FdsStick(transport).write_raw_side(bytes(WRITE_PAYLOAD * 10))

    assert raised.value.kind is FaultKind.LINK


def test_a_device_that_stops_once_the_disk_has_turned_is_not_a_fault() -> None:
    transport = RefusingTransport(accept=SETTLED_PACKETS)

    FdsStick(transport).write_raw_side(bytes(WRITE_PAYLOAD * (SETTLED_PACKETS + 5)))

    assert len(transport.outputs) == SETTLED_PACKETS


def test_a_disk_that_never_ends_stops_at_the_raw_ceiling() -> None:
    full = deque(
        bytes([ReportId.DISK_CHUNK, (index % SEQUENCE_WRAP) + 1]) + bytes(CHUNK_PAYLOAD)
        for index in range(RAW_SIDE_LIMIT // CHUNK_PAYLOAD + 2)
    )
    transport = RecordingTransport({ReportId.DISK_CHUNK: full})

    assert len(FdsStick(transport).read_raw_side()) >= RAW_SIDE_LIMIT
