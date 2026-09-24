from __future__ import annotations

import importlib
from collections.abc import Iterator, Sequence
from enum import IntEnum
from typing import Final, Protocol, cast, runtime_checkable

from fdstoolkit.codecs.raw import decode_raw03, encode_block_stream, unpack_raw03
from fdstoolkit.hardware.ports import BlockRead, DriveStatus, FaultKind, HardwareFaultError

VENDOR_ID: Final = 0x16D0
PRODUCT_ID: Final = 0x0AAA
PRODUCT_STRING: Final = "FDSStick"

CHUNK_PAYLOAD: Final = 0xFE
WRITE_PAYLOAD: Final = 0xFF
WRITE_REPORT_LENGTH: Final = 0x100
RAW_SIDE_LIMIT: Final = 0x23F02
HEADER_BYTES: Final = 2
SEQUENCE_WRAP: Final = 0xFF
MODE_READ: Final = 0x00
MODE_WRITE: Final = 0x01
SETTLED_PACKETS: Final = 400


class ReportId(IntEnum):
    DISK_START = 0x10
    DISK_CHUNK = 0x11
    DISK_WRITE = 0x12


@runtime_checkable
class HidTransport(Protocol):
    def send_feature(self, data: bytes) -> None: ...

    def get_feature(self, report_id: int, length: int) -> bytes: ...

    def write_output(self, data: bytes) -> None: ...

    def close(self) -> None: ...


class FdsStick:
    reports_write_protection: Final = False
    selects_sides: Final = False

    def __init__(self, transport: HidTransport, *, assume_writable: bool = False) -> None:
        self._transport = transport
        self._captures: list[bytes] = []
        self._assume_writable = assume_writable

    @property
    def captures(self) -> tuple[bytes, ...]:
        return tuple(self._captures)

    def close(self) -> None:
        self._transport.close()

    def status(self) -> DriveStatus:
        return DriveStatus(
            disk_present=None,
            write_protected=None,
            battery_ok=None,
            ready=None,
            assume_writable=self._assume_writable,
        )

    def _start(self, mode: int) -> None:
        self._transport.send_feature(bytes([ReportId.DISK_START, mode]))

    def read_raw_side(self) -> bytes:
        self._start(MODE_READ)
        out = bytearray()
        expected = 1

        while len(out) < RAW_SIDE_LIMIT:
            packet = self._transport.get_feature(ReportId.DISK_CHUNK, CHUNK_PAYLOAD + 3)
            if len(packet) < HEADER_BYTES:
                message = "the device stopped answering during the read"
                raise HardwareFaultError(message, kind=FaultKind.LINK)

            sequence = packet[1]
            payload = packet[HEADER_BYTES : HEADER_BYTES + CHUNK_PAYLOAD]
            if sequence != expected:
                message = f"data was lost: expected packet {expected}, the device sent {sequence}"
                raise HardwareFaultError(message, kind=FaultKind.MEDIA)
            expected = 1 if sequence == SEQUENCE_WRAP else sequence + 1

            out += payload
            if len(payload) < CHUNK_PAYLOAD:
                break

        return bytes(out)

    def write_raw_side(self, values: bytes) -> None:
        self._start(MODE_WRITE)
        for index, start in enumerate(range(0, len(values), WRITE_PAYLOAD)):
            chunk = values[start : start + WRITE_PAYLOAD]
            packet = bytes([ReportId.DISK_WRITE]) + chunk.ljust(WRITE_PAYLOAD, b"\0")
            try:
                self._transport.write_output(packet)
            except OSError as error:
                if index < SETTLED_PACKETS:
                    message = f"the device stopped accepting data after {index} packet(s)"
                    raise HardwareFaultError(message, kind=FaultKind.LINK) from error
                break

    def read_side(self, side: int) -> Iterator[BlockRead]:
        del side
        packed = self.read_raw_side()
        self._captures.append(packed)
        values = unpack_raw03(packed)
        decoded, _ = decode_raw03(values)
        for index, block in enumerate(decoded.blocks):
            yield BlockRead(
                index=index,
                payload=block.payload,
                crc_ok=block.stored_crc == block.computed_crc,
                attempts=1,
            )

    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        del side
        self.write_raw_side(encode_block_stream(blocks))


@runtime_checkable
class HidDevice(Protocol):
    def open(self, vendor_id: int, product_id: int) -> None: ...

    def send_feature_report(self, data: bytes) -> int: ...

    def get_feature_report(self, report_id: int, length: int) -> list[int]: ...

    def write(self, data: bytes) -> int: ...

    def close(self) -> None: ...


class HidApiTransport:
    def __init__(self, device: HidDevice) -> None:
        self._device = device

    def send_feature(self, data: bytes) -> None:
        self._device.send_feature_report(data)

    def get_feature(self, report_id: int, length: int) -> bytes:
        answer = bytes(self._device.get_feature_report(report_id, length))
        if answer[:1] == bytes([report_id]):
            return answer
        return bytes([report_id]) + answer

    def write_output(self, data: bytes) -> None:
        self._device.write(data)

    def close(self) -> None:
        self._device.close()


@runtime_checkable
class HidModule(Protocol):
    def device(self) -> HidDevice: ...


def _load_hid() -> HidModule:
    return cast("HidModule", importlib.import_module("hid"))


def open_fdsstick(*, assume_writable: bool = False) -> FdsStick:
    try:
        hid = _load_hid()
    except ImportError as error:
        message = (
            "hidapi is not installed, so an FDSStick cannot be opened. "
            "Install the hardware extra: uv pip install 'fdstoolkit[hardware]'"
        )
        raise HardwareFaultError(message, kind=FaultKind.LINK) from error

    device = hid.device()
    try:
        device.open(VENDOR_ID, PRODUCT_ID)
    except OSError as error:
        message = (
            f"no FDSStick answered at {VENDOR_ID:#06x}:{PRODUCT_ID:#06x}. "
            "Check the USB cable and that no other program holds the device"
        )
        raise HardwareFaultError(message, kind=FaultKind.LINK) from error

    return FdsStick(HidApiTransport(device), assume_writable=assume_writable)
