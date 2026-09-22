from __future__ import annotations

from collections import deque

import pytest

from fdstk.build.blank import blank_image
from fdstk.codecs.fds import decode as decode_fds
from fdstk.codecs.raw import encode_raw03
from fdstk.hardware.fdsstick import (
    BULK_READ_PAYLOAD,
    BULK_WRITE_PAYLOAD,
    PRODUCT_ID,
    VENDOR_ID,
    FdsStick,
    ReportId,
)
from fdstk.hardware.ports import FaultKind, HardwareFaultError


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
    for start in range(0, len(payload), BULK_READ_PAYLOAD):
        chunk = payload[start : start + BULK_READ_PAYLOAD]
        packets.append(bytes([ReportId.BULK_READ, sequence]) + chunk)
        sequence = 1 if sequence == 0xFF else sequence + 1
    packets.append(bytes([ReportId.BULK_READ, sequence]))
    return packets


def test_the_device_identity_is_the_documented_one() -> None:
    assert VENDOR_ID == 0x16D0
    assert PRODUCT_ID == 0x0AAA


def test_the_handshake_probes_the_flash_and_reads_status() -> None:
    transport = FakeTransport()

    FdsStick(transport).handshake()

    commands = [feature[0] for feature in transport.features]
    assert commands.count(ReportId.COMMAND) >= 3
    assert transport.features[0][1] == 0x01
    assert transport.features[0][2] == 0x9F


def test_a_bulk_read_returns_the_payload_of_every_packet() -> None:
    payload = bytes(range(256)) * 4
    transport = FakeTransport({ReportId.BULK_READ: read_packets(payload)})

    values = FdsStick(transport).read_raw_side()

    assert values == payload


def test_a_bulk_read_starts_the_device_in_read_mode() -> None:
    transport = FakeTransport({ReportId.BULK_READ: read_packets(bytes(16))})

    FdsStick(transport).read_raw_side()

    assert bytes([ReportId.MODE, 0x00]) in transport.features


def test_a_short_packet_ends_the_read() -> None:
    packets: deque[bytes] = deque(
        [
            bytes([ReportId.BULK_READ, 1]) + bytes(BULK_READ_PAYLOAD),
            bytes([ReportId.BULK_READ, 2]) + bytes(10),
            bytes([ReportId.BULK_READ, 3]) + bytes(BULK_READ_PAYLOAD),
        ]
    )
    transport = FakeTransport({ReportId.BULK_READ: packets})

    values = FdsStick(transport).read_raw_side()

    assert len(values) == BULK_READ_PAYLOAD + 10


def test_a_skipped_sequence_byte_is_reported_as_lost_data() -> None:
    packets: deque[bytes] = deque(
        [
            bytes([ReportId.BULK_READ, 1]) + bytes(BULK_READ_PAYLOAD),
            bytes([ReportId.BULK_READ, 9]) + bytes(BULK_READ_PAYLOAD),
        ]
    )
    transport = FakeTransport({ReportId.BULK_READ: packets})

    with pytest.raises(HardwareFaultError) as caught:
        FdsStick(transport).read_raw_side()

    assert caught.value.kind is FaultKind.MEDIA
    assert "lost" in str(caught.value)


def test_a_stale_first_packet_is_discarded() -> None:
    packets: deque[bytes] = deque(
        [
            bytes([ReportId.BULK_READ, 7]) + bytes(BULK_READ_PAYLOAD),
            bytes([ReportId.BULK_READ, 1]) + bytes(BULK_READ_PAYLOAD),
            bytes([ReportId.BULK_READ, 2]) + bytes(10),
        ]
    )
    transport = FakeTransport({ReportId.BULK_READ: packets})

    values = FdsStick(transport).read_raw_side()

    assert len(values) == BULK_READ_PAYLOAD + 10


def test_a_truncated_response_is_a_link_fault() -> None:
    transport = FakeTransport({ReportId.BULK_READ: deque([bytes([ReportId.BULK_READ])])})

    with pytest.raises(HardwareFaultError) as caught:
        FdsStick(transport).read_raw_side()

    assert caught.value.kind is FaultKind.LINK


def test_writing_sends_full_packets_and_finalises() -> None:
    transport = FakeTransport()
    disk = sample_disk()

    FdsStick(transport).write_raw_side(encode_raw03(disk, side=0))

    assert bytes([ReportId.MODE, 0x01]) in transport.features
    assert all(len(packet) == BULK_WRITE_PAYLOAD + 1 for packet in transport.outputs)
    assert transport.outputs[0][0] == ReportId.BULK_WRITE
    assert transport.features[-1] == bytes([ReportId.FINALISE, 0x00])


def test_a_short_final_packet_is_padded_rather_than_sent_short() -> None:
    transport = FakeTransport()

    FdsStick(transport).write_raw_side(bytes([0x55]) * (BULK_WRITE_PAYLOAD + 3))

    assert len(transport.outputs) == 2
    assert len(transport.outputs[1]) == BULK_WRITE_PAYLOAD + 1


def test_reading_a_side_yields_blocks_with_their_crc_verdict() -> None:
    disk = sample_disk()
    payload = encode_raw03(disk, side=0)
    transport = FakeTransport({ReportId.BULK_READ: read_packets(payload)})

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
