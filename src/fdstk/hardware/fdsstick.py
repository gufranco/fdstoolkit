from __future__ import annotations

import importlib
from collections.abc import Iterator, Sequence
from enum import IntEnum
from typing import Final, Protocol, cast, runtime_checkable

from fdstk.codecs.raw import decode_raw03, encode_block_stream, unpack_raw03
from fdstk.hardware.ports import BlockRead, DriveStatus, FaultKind, HardwareFaultError

VENDOR_ID: Final = 0x16D0
PRODUCT_ID: Final = 0x0AAA

BULK_READ_PAYLOAD: Final = 254
BULK_WRITE_PAYLOAD: Final = 255
STATUS_LENGTH: Final = 64
DEVICE_STATUS_LENGTH: Final = 65
COMMAND_LENGTH: Final = 64
BLOCK_STATUS_LENGTH: Final = 257
VERIFY_LENGTH: Final = 514
FILL_BYTE: Final = 0x63
MAX_PACKETS_PER_SIDE: Final = 512
HEADER_BYTES: Final = 2
SEQUENCE_WRAP: Final = 0xFF
MODE_READ: Final = 0x00
MODE_WRITE: Final = 0x01

ADDRESS_FIRST: Final = 0x01B0
ADDRESS_LAST: Final = 0x04E0
ADDRESS_STEP: Final = 0x10
ADDRESS_TRAILER: Final = 0xD8

PROBE_OPCODES: Final = (0x9F, 0x05, 0x15)


class ReportId(IntEnum):
    BLOCK_STATUS = 0x01
    STATUS = 0x02
    COMMAND = 0x03
    TRIGGER = 0x04
    ADDRESS = 0x06
    VERIFY_A = 0x08
    VERIFY_B = 0x09
    MODE = 0x10
    BULK_READ = 0x11
    BULK_WRITE = 0x12
    FINALISE = 0x20
    DEVICE_STATUS = 0x21


@runtime_checkable
class HidTransport(Protocol):
    def send_feature(self, data: bytes) -> None: ...

    def get_feature(self, report_id: int, length: int) -> bytes: ...

    def write_output(self, data: bytes) -> None: ...

    def close(self) -> None: ...


class FdsStick:
    def __init__(self, transport: HidTransport) -> None:
        self._transport = transport
        self._captures: list[bytes] = []

    @property
    def captures(self) -> tuple[bytes, ...]:
        return tuple(self._captures)

    reports_write_protection: Final = False

    def close(self) -> None:
        self._transport.close()

    def status(self) -> DriveStatus:
        return DriveStatus(
            disk_present=True,
            write_protected=False,
            battery_ok=True,
            ready=True,
        )

    def _command(self, opcode: int, fill: int) -> None:
        body = bytearray([ReportId.COMMAND, 0x01, opcode, fill])
        body += bytes([fill or 0x00]) * (COMMAND_LENGTH - len(body))
        self._transport.send_feature(bytes(body))

    def _status(self) -> bytes:
        return self._transport.get_feature(ReportId.STATUS, STATUS_LENGTH + 1)

    def _device_status(self) -> bytes:
        return self._transport.get_feature(ReportId.DEVICE_STATUS, DEVICE_STATUS_LENGTH)

    def _init_sequence(self, fill: int) -> None:
        self._command(PROBE_OPCODES[0], fill)
        self._status()
        self._device_status()
        for opcode in PROBE_OPCODES[1:]:
            self._command(opcode, 0x00)
            self._status()

    def _set_address(self, address: int) -> None:
        self._transport.send_feature(
            bytes([ReportId.ADDRESS, address & 0xFF, (address >> 8) & 0xFF, ADDRESS_TRAILER]),
        )

    def _trigger(self) -> None:
        self._transport.send_feature(
            bytes([ReportId.TRIGGER, 0x01, 0x01, 0x03, 0x05, *([FILL_BYTE] * 4)]),
        )

    def _acknowledge(self) -> None:
        self._transport.send_feature(
            bytes([ReportId.TRIGGER, 0x00, 0x00, 0x00, 0x05, *([FILL_BYTE] * 4)]),
        )

    def scan_address_table(self) -> None:
        for address in range(ADDRESS_FIRST, ADDRESS_LAST + 1, ADDRESS_STEP):
            self._set_address(address)
            self._trigger()
            self._transport.get_feature(ReportId.BLOCK_STATUS, BLOCK_STATUS_LENGTH)
            self._acknowledge()

    def handshake(self) -> None:
        self._init_sequence(0x00)
        self._init_sequence(FILL_BYTE)
        self._transport.get_feature(ReportId.VERIFY_A, VERIFY_LENGTH)
        self._transport.get_feature(ReportId.VERIFY_B, VERIFY_LENGTH)

    def _start(self, mode: int) -> None:
        self._transport.send_feature(bytes([ReportId.MODE, mode]))

    def read_raw_side(self) -> bytes:
        self._start(MODE_READ)
        out = bytearray()
        expected = 1
        first = True

        for _ in range(MAX_PACKETS_PER_SIDE):
            packet = self._transport.get_feature(ReportId.BULK_READ, BULK_READ_PAYLOAD + 3)
            if len(packet) < HEADER_BYTES:
                message = "the device stopped answering during the read"
                raise HardwareFaultError(message, kind=FaultKind.LINK)

            sequence = packet[1]
            payload = packet[HEADER_BYTES:]
            if first and sequence != expected:
                first = False
                continue
            first = False

            if sequence != expected:
                message = f"data was lost: expected packet {expected}, the device sent {sequence}"
                raise HardwareFaultError(message, kind=FaultKind.MEDIA)
            expected = 1 if sequence == SEQUENCE_WRAP else sequence + 1

            out += payload
            if len(payload) < BULK_READ_PAYLOAD:
                break

        return bytes(out)

    def write_raw_side(self, values: bytes) -> None:
        self._start(MODE_WRITE)
        for start in range(0, len(values), BULK_WRITE_PAYLOAD):
            chunk = values[start : start + BULK_WRITE_PAYLOAD]
            packet = bytes([ReportId.BULK_WRITE]) + chunk.ljust(BULK_WRITE_PAYLOAD, b"\0")
            self._transport.write_output(packet)
        self._transport.send_feature(bytes([ReportId.FINALISE, 0x00]))

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


def open_fdsstick() -> FdsStick:
    try:
        hid = _load_hid()
    except ImportError as error:
        message = (
            "hidapi is not installed, so an FDSStick cannot be opened. "
            "Install the hardware extra: uv pip install 'fdstk[hardware]'"
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

    stick = FdsStick(HidApiTransport(device))
    stick.handshake()
    return stick
