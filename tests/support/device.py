from __future__ import annotations

from dataclasses import dataclass, field

from fdstoolkit.codecs.raw import decode_write_stream, encode_block_stream

CHUNK_PAYLOAD = 0xFE
WRITE_PAYLOAD = 0xFF
SEQUENCE_MASK = 0xFF
FIRST_SEQUENCE = 1

ID_DISK_START = 0x10
ID_DISK_CHUNK = 0x11
ID_DISK_WRITE = 0x12
ID_FINISH_WRITE = 0x20

MODE_READ = 0x00
MODE_WRITE = 0x01


UNPLUGGED = "device unplugged"


class DeviceRefusedError(OSError):
    pass


@dataclass
class FakeFdsStick:
    """A stand-in for the device, modelled on what the two reference tools expect of it.

    It serves a raw side in 254-byte chunks numbered with a wrapping counter, the way
    the Rust tool's wrapping_add reads them, and it stops accepting write data once the
    disk has turned, which is the condition that tool treats as a full disk. Like hidapi
    on a real stick, a refused write packet returns -1 rather than raising, and a read
    started right after a finished write fails until the stick has settled, after a
    stale first reply when one is set. A stick
    pulled from the port raises from then on, on reads and writes alike.
    """

    side: bytes = b""
    stale_first: int | None = None
    drop_after: int | None = None
    pads_last_chunk: bool = False
    accepts_writes: int | None = None
    refused_packets: tuple[int, ...] = ()
    busy_reads_after_finish: int = 0
    unplugged_at: int | None = None
    short_reply: bool = False
    echoes: bool = False

    opened: tuple[int, int] | None = None
    closed: bool = False
    mode: int | None = None
    served: int = 0
    written: bytearray = field(default_factory=bytearray)
    starts: list[int] = field(default_factory=list[int])
    seen: list[int] = field(default_factory=list[int])
    finishes: list[bytes] = field(default_factory=list[bytes])
    refusals: list[int] = field(default_factory=list[int])
    busy_left: int = 0

    def open(self, vendor_id: int, product_id: int) -> None:
        self.opened = (vendor_id, product_id)

    def close(self) -> None:
        self.closed = True

    def send_feature_report(self, data: bytes) -> int:
        self.seen.append(data[0])
        if data[0] == ID_FINISH_WRITE:
            self.finishes.append(bytes(data))
            self.busy_left = self.busy_reads_after_finish
        if data[0] == ID_DISK_START:
            self.mode = data[1]
            self.starts.append(data[1])
            self.served = 0
            self._turn_over_the_write(data[1])
        return len(data)

    def _turn_over_the_write(self, mode: int) -> None:
        if mode == MODE_WRITE:
            self.written = bytearray()
        elif self.echoes and self.written:
            self.side = encode_block_stream(decode_write_stream(bytes(self.written)))

    def write(self, data: bytes) -> int:
        self.seen.append(data[0])
        if data[0] != ID_DISK_WRITE:
            message = f"the device was sent report {data[0]:#04x} on the output endpoint"
            raise DeviceRefusedError(message)
        packet = len(self.written) // WRITE_PAYLOAD
        if self.unplugged_at is not None and packet >= self.unplugged_at:
            raise DeviceRefusedError(UNPLUGGED)
        if self.accepts_writes is not None and packet >= self.accepts_writes:
            return -1
        if packet in self.refused_packets and packet not in self.refusals:
            self.refusals.append(packet)
            return -1
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
        if self.unplugged_at is not None and self.served >= self.unplugged_at:
            raise DeviceRefusedError(UNPLUGGED)
        if self.busy_left:
            if self.stale_first is not None and self.served == 0:
                return list(self._chunk())
            self.busy_left -= 1
            message = "read error"
            raise DeviceRefusedError(message)
        return list(self._chunk())

    def _sequence(self) -> int:
        if self.stale_first is not None and self.served == 0:
            return self.stale_first
        counted = self.served + FIRST_SEQUENCE
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
