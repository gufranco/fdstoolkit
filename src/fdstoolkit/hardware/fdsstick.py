from __future__ import annotations

import importlib
from collections.abc import Iterator, Sequence
from enum import IntEnum
from typing import Final, Protocol, cast, runtime_checkable

from fdstoolkit.codecs.raw import decode_raw03, encode_block_stream, unpack_raw03
from fdstoolkit.drive.captures import Capture
from fdstoolkit.hardware.ports import BlockRead, DriveStatus, FaultKind, HardwareFaultError
from fdstoolkit.hardware.watchdog import UNMEASURED_CEILING_S, Watchdog

VENDOR_ID: Final = 0x16D0
PRODUCT_ID: Final = 0x0AAA
PRODUCT_STRING: Final = "FDSStick"

CHUNK_PAYLOAD: Final = 0xFE
WRITE_PAYLOAD: Final = 0xFF
WRITE_REPORT_LENGTH: Final = 0x100
RAW_SIDE_LIMIT: Final = 0x23F02
HEADER_BYTES: Final = 2
SEQUENCE_MASK: Final = 0xFF
FIRST_SEQUENCE: Final = 1
MODE_READ: Final = 0x00
MODE_WRITE: Final = 0x01
SETTLED_PACKETS: Final = 400

LEGACY_REPORTS: Final = (0x11, 0x12, 0x13, 0x14)

OLDER_FIRMWARE_HINT: Final = (
    "the device answered but sent no disk data. Firmware from 2015 numbers these "
    f"reports {LEGACY_REPORTS} and takes no mode byte, which this driver does not "
    "speak. Check the firmware version doctor reports"
)


def _after(sequence: int) -> int:
    return (sequence + 1) & SEQUENCE_MASK


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

    def __init__(self, transport: HidTransport, *, ceiling: float = UNMEASURED_CEILING_S) -> None:
        self._transport = transport
        self._watchdog = Watchdog(on_stall=self.close, ceiling=ceiling)
        self._captures: list[Capture] = []
        self._resyncs: list[tuple[int, int]] = []

    @property
    def captures(self) -> tuple[Capture, ...]:
        return tuple(self._captures)

    @property
    def resyncs(self) -> tuple[tuple[int, int], ...]:
        return tuple(self._resyncs)

    def close(self) -> None:
        self._transport.close()

    def status(self) -> DriveStatus:
        return DriveStatus(
            disk_present=None,
            write_protected=None,
            battery_ok=None,
            ready=None,
        )

    @property
    def watchdog(self) -> Watchdog:
        return self._watchdog

    def _start(self, mode: int) -> None:
        start = bytes([ReportId.DISK_START, mode])
        self._watchdog.call(lambda: self._transport.send_feature(start))

    def _chunk(self) -> bytes:
        return self._watchdog.call(
            lambda: self._transport.get_feature(ReportId.DISK_CHUNK, CHUNK_PAYLOAD + 3)
        )

    def read_raw_side(self, *, what: str = "reading a side", mode: int = MODE_READ) -> bytes:
        with self._watchdog.side(what):
            return self._read_raw(mode)

    def _read_raw(self, mode: int) -> bytes:
        self._start(mode)
        out = bytearray()
        expected = FIRST_SEQUENCE
        opening = True

        while len(out) < RAW_SIDE_LIMIT:
            packet = self._chunk()
            if len(packet) < HEADER_BYTES:
                message = "the device stopped answering during the read"
                raise HardwareFaultError(message, kind=FaultKind.LINK)

            sequence = packet[1]
            payload = packet[HEADER_BYTES : HEADER_BYTES + CHUNK_PAYLOAD]
            if not payload:
                if not out:
                    raise HardwareFaultError(OLDER_FIRMWARE_HINT, kind=FaultKind.MEDIA)
                break

            if opening and sequence != FIRST_SEQUENCE:
                expected = _after(sequence)
                opening = False
                continue
            opening = False

            if sequence != expected:
                self._resyncs.append((expected, sequence))
            expected = _after(sequence)

            out += payload
            if len(payload) < CHUNK_PAYLOAD:
                break

        return bytes(out)

    def write_raw_side(self, values: bytes, *, what: str = "writing a side") -> None:
        with self._watchdog.side(what, writing=True):
            self._write_raw(values)

    def _write_raw(self, values: bytes) -> None:
        self._start(MODE_WRITE)
        for index, start in enumerate(range(0, len(values), WRITE_PAYLOAD)):
            chunk = values[start : start + WRITE_PAYLOAD]
            packet = bytes([ReportId.DISK_WRITE]) + chunk.ljust(WRITE_PAYLOAD, b"\0")
            try:
                self._watchdog.call(lambda packet=packet: self._transport.write_output(packet))
            except OSError as error:
                if index < SETTLED_PACKETS:
                    message = f"the device stopped accepting data after {index} packet(s)"
                    raise HardwareFaultError(message, kind=FaultKind.LINK) from error
                break

    def read_side(self, side: int) -> Iterator[BlockRead]:
        packed = self.read_raw_side(what=f"reading side {side}")
        read = sum(1 for capture in self._captures if capture.side == side) + 1
        self._captures.append(Capture(side=side, read=read, data=packed))
        values = unpack_raw03(packed)
        decoded, _ = decode_raw03(values)
        for index, block in enumerate(decoded.blocks):
            yield BlockRead(
                index=index,
                payload=block.payload,
                crc_ok=block.stored_crc == block.computed_crc,
                attempts=1,
                stored_crc=block.stored_crc,
            )

    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        self.write_raw_side(encode_block_stream(blocks), what=f"writing side {side}")


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
            "Homebrew installs it with the toolkit: brew reinstall gufranco/fdstoolkit/fdstoolkit"
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

    return FdsStick(HidApiTransport(device))
