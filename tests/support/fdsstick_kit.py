from __future__ import annotations

import threading
from collections import deque

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode as decode_fds
from fdstoolkit.hardware.fdsstick import (
    CHUNK_PAYLOAD,
    ReportId,
)


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
