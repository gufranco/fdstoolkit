from __future__ import annotations

from dataclasses import dataclass, field

CHUNK_PAYLOAD = 0xFE
WRITE_PAYLOAD = 0xFF
SEQUENCE_MASK = 0xFF
FIRST_SEQUENCE = 1

ID_DISK_START = 0x10
ID_DISK_CHUNK = 0x11
ID_DISK_WRITE = 0x12

MODE_READ = 0x00
MODE_WRITE = 0x01


class DeviceRefusedError(OSError):
    pass


@dataclass
class FakeFdsStick:
    """A stand-in for the device, modelled on what the two reference tools expect of it.

    It serves a raw side in 254-byte chunks numbered with a wrapping counter, the way
    the Rust tool's wrapping_add reads them, and it stops accepting write data once the
    disk has turned, which is the condition that tool treats as a full disk.
    """

    side: bytes = b""
    stale_first: int | None = None
    drop_after: int | None = None
    pads_last_chunk: bool = False
    accepts_writes: int | None = None
    short_reply: bool = False

    opened: tuple[int, int] | None = None
    closed: bool = False
    mode: int | None = None
    served: int = 0
    written: bytearray = field(default_factory=bytearray)
    starts: list[int] = field(default_factory=list[int])
    seen: list[int] = field(default_factory=list[int])

    def open(self, vendor_id: int, product_id: int) -> None:
        self.opened = (vendor_id, product_id)

    def close(self) -> None:
        self.closed = True

    def send_feature_report(self, data: bytes) -> int:
        self.seen.append(data[0])
        if data[0] == ID_DISK_START:
            self.mode = data[1]
            self.starts.append(data[1])
            self.served = 0
        return len(data)

    def write(self, data: bytes) -> int:
        self.seen.append(data[0])
        if data[0] != ID_DISK_WRITE:
            message = f"the device was sent report {data[0]:#04x} on the output endpoint"
            raise DeviceRefusedError(message)
        if (
            self.accepts_writes is not None
            and len(self.written) // WRITE_PAYLOAD >= self.accepts_writes
        ):
            message = "the disk has turned and the device is no longer accepting data"
            raise DeviceRefusedError(message)
        self.written += data[1:]
        return len(data)

    def get_feature_report(self, report_id: int, length: int) -> list[int]:
        del length
        self.seen.append(report_id)
        if report_id != ID_DISK_CHUNK:
            message = f"the device was asked for report {report_id:#04x}"
            raise DeviceRefusedError(message)
        if self.short_reply:
            return [report_id]
        return list(self._chunk())

    def _sequence(self) -> int:
        if self.stale_first is not None and self.served == 0:
            return self.stale_first
        offset = 0 if self.stale_first is None else 1
        counted = self.served + FIRST_SEQUENCE - offset
        if self.drop_after is not None and self.served > self.drop_after:
            counted += 1
        return counted & SEQUENCE_MASK

    def _body(self) -> bytes:
        if self.stale_first is not None and self.served == 0:
            return bytes(CHUNK_PAYLOAD)
        taken = self.served if self.stale_first is None else self.served - 1
        start = taken * CHUNK_PAYLOAD
        body = self.side[start : start + CHUNK_PAYLOAD]
        if len(body) < CHUNK_PAYLOAD and self.pads_last_chunk:
            return body.ljust(CHUNK_PAYLOAD, b"\x00") if body else b""
        return body

    def _chunk(self) -> bytes:
        sequence = self._sequence()
        body = self._body()
        self.served += 1
        return bytes([ID_DISK_CHUNK, sequence]) + body
