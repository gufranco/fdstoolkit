from __future__ import annotations

import importlib
import logging
import time
from collections.abc import Callable, Iterator, Sequence
from enum import IntEnum
from typing import Final, Protocol, cast, runtime_checkable

from fdstoolkit.codecs.raw import decode_packed
from fdstoolkit.codecs.write_stream import (
    WRITE_FILL,
    WRITE_GAP_BYTE,
    WRITE_HEADER,
    WRITE_LEAD_IN_BYTES,
    encode_write_stream,
)
from fdstoolkit.drive.captures import Capture
from fdstoolkit.drive.pulse import PulseFinding, findings_of
from fdstoolkit.hardware.device_lock import DriveLock, acquire_drive_lock
from fdstoolkit.hardware.ports import BlockRead, DriveStatus, FaultKind, HardwareFaultError
from fdstoolkit.hardware.watchdog import UNMEASURED_CEILING_S, Watchdog

VENDOR_ID: Final = 0x16D0
PRODUCT_ID: Final = 0x0AAA

CHUNK_PAYLOAD: Final = 0xFE
WRITE_PAYLOAD: Final = 0xFF
WRITE_REPORT_LENGTH: Final = 0x100
RAW_SIDE_LIMIT: Final = 0x23F02
HEADER_BYTES: Final = 2
SEQUENCE_MASK: Final = 0xFF
FIRST_SEQUENCE: Final = 1
MODE_READ: Final = 0x00
MODE_WRITE: Final = 0x01
BLANKED_PACKETS: Final = 700
PACKET_ATTEMPTS: Final = 2
READS_AFTER_WRITE: Final = 8
WRITE_STARTS: Final = 8
SETTLE_PAUSE_S: Final = 2.0
LEAD_IN_PACKETS: Final = (len(WRITE_HEADER) + WRITE_LEAD_IN_BYTES) // WRITE_PAYLOAD
PACKET_PAD: Final = bytes([WRITE_GAP_BYTE])

logger = logging.getLogger(__name__)

LEGACY_REPORTS: Final = (0x11, 0x12, 0x13, 0x14)

OLDER_FIRMWARE_HINT: Final = (
    "the device answered but sent no disk data. Firmware from 2015 numbers these "
    f"reports {LEGACY_REPORTS} and takes no mode byte, which this driver does not "
    "speak. Check the firmware version doctor reports"
)


def link_note(resyncs: Sequence[tuple[int, int]]) -> str:
    if not resyncs:
        return ""
    return (
        f"the USB link skipped {len(resyncs)} packet(s) of pulse data during the reads, so a "
        "block failing near one may be the link rather than the disk. Read it again before "
        "blaming the disk"
    )


def _after(sequence: int) -> int:
    return (sequence + 1) & SEQUENCE_MASK


def _link_lost(what: str, error: OSError) -> str:
    return (
        f"the stick failed {what} ({error}). Unplug it, plug it back in and run the command again"
    )


class DriveNotReadyError(HardwareFaultError):
    def __init__(self, packets: int) -> None:
        message = (
            f"the device stopped accepting data after {packets} packet(s), inside the "
            "lead-in, so the drive never became ready to write and no block was written"
        )
        super().__init__(message, kind=FaultKind.LINK)


class NothingReadError(HardwareFaultError):
    def __init__(self, error: OSError) -> None:
        super().__init__(_link_lost("to start a read", error), kind=FaultKind.LINK)


class ReportId(IntEnum):
    DISK_START = 0x10
    DISK_CHUNK = 0x11
    DISK_WRITE = 0x12
    FINISH_WRITE = 0x20


def _packets(values: bytes) -> tuple[bytes, ...]:
    return tuple(
        bytes([ReportId.DISK_WRITE])
        + values[start : start + WRITE_PAYLOAD].ljust(WRITE_PAYLOAD, PACKET_PAD)
        for start in range(0, len(values), WRITE_PAYLOAD)
    )


def _blank_packet() -> bytes:
    return bytes([ReportId.DISK_WRITE]) + WRITE_FILL * (WRITE_PAYLOAD // len(WRITE_FILL))


@runtime_checkable
class HidTransport(Protocol):
    def send_feature(self, data: bytes) -> None: ...

    def get_feature(self, report_id: int, length: int) -> bytes: ...

    def write_output(self, data: bytes) -> int: ...

    def close(self) -> None: ...


class FdsStick:
    reports_write_protection: Final = False
    selects_sides: Final = False

    def __init__(
        self,
        transport: HidTransport,
        *,
        ceiling: float = UNMEASURED_CEILING_S,
        lock: DriveLock | None = None,
        pause: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport
        self._pause = pause
        self._lock = lock
        self._watchdog = Watchdog(on_stall=self.close, ceiling=ceiling)
        self._captures: list[Capture] = []
        self._resyncs: list[tuple[int, int]] = []
        self._pulse: list[PulseFinding] = []
        self._written = False

    @property
    def captures(self) -> tuple[Capture, ...]:
        return tuple(self._captures)

    @property
    def resyncs(self) -> tuple[tuple[int, int], ...]:
        return tuple(self._resyncs)

    @property
    def pulse_findings(self) -> tuple[PulseFinding, ...]:
        return tuple(self._pulse)

    def close(self) -> None:
        self._transport.close()
        if self._lock is not None:
            self._lock.release()

    @property
    def closed_lock(self) -> bool:
        return self._lock is None or self._lock.released

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
        self._transport.send_feature(bytes([ReportId.DISK_START, mode]))

    def _chunk(self, *, opening: bool) -> bytes:
        try:
            return self._transport.get_feature(ReportId.DISK_CHUNK, CHUNK_PAYLOAD + 3)
        except OSError as error:
            if opening:
                raise NothingReadError(error) from error
            raise HardwareFaultError(
                _link_lost("during a read", error), kind=FaultKind.LINK
            ) from error

    def read_raw_side(self, *, what: str = "reading a side", mode: int = MODE_READ) -> bytes:
        retries = READS_AFTER_WRITE - 1 if self._written else 0
        self._written = False
        for _ in range(retries):
            try:
                return self._watched_read(what, mode)
            except NothingReadError:
                self._pause(SETTLE_PAUSE_S)
        return self._watched_read(what, mode)

    def _watched_read(self, what: str, mode: int) -> bytes:
        with self._watchdog.side(what):
            return self._watchdog.call(lambda: self._read_raw(mode))

    def _read_raw(self, mode: int) -> bytes:
        self._start(mode)
        out = bytearray()
        expected = FIRST_SEQUENCE
        opening = True

        while len(out) < RAW_SIDE_LIMIT:
            packet = self._chunk(opening=not out)
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
                expected = _after(FIRST_SEQUENCE)
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

    def write_raw_side(
        self, values: bytes, *, what: str = "writing a side", fill_to: int = 0
    ) -> None:
        packets = _packets(values)
        blank = (_blank_packet(),) * max(fill_to - len(packets), 0)
        for _ in range(WRITE_STARTS - 1):
            try:
                self._watched_write(packets, blank, what)
            except DriveNotReadyError:
                self._pause(SETTLE_PAUSE_S)
                continue
            return
        self._watched_write(packets, blank, what)

    def _watched_write(
        self, packets: tuple[bytes, ...], blank: tuple[bytes, ...], what: str
    ) -> None:
        with self._watchdog.side(what, writing=True):
            self._watchdog.call(lambda: self._write_and_finish(packets, blank))
            self._written = True

    def _write_and_finish(self, packets: tuple[bytes, ...], blank: tuple[bytes, ...]) -> None:
        self._write_raw(packets, blank)
        self._transport.send_feature(bytes([ReportId.FINISH_WRITE, 0x00]))

    def _write_raw(self, packets: tuple[bytes, ...], blank: tuple[bytes, ...]) -> None:
        self._start(MODE_WRITE)
        for index, packet in enumerate((*packets, *blank)):
            if self._delivered(packet):
                continue
            if index < LEAD_IN_PACKETS:
                raise DriveNotReadyError(index)
            if index < len(packets):
                message = (
                    f"the device stopped accepting data after {index} of {len(packets)} "
                    "packet(s), so the side holds only part of the image"
                )
                raise HardwareFaultError(message, kind=FaultKind.LINK)
            break

    def _delivered(self, packet: bytes) -> bool:
        for _ in range(PACKET_ATTEMPTS):
            try:
                taken = self._transport.write_output(packet)
            except OSError as error:
                raise HardwareFaultError(
                    _link_lost("during a write", error), kind=FaultKind.LINK
                ) from error
            if taken >= 0:
                return True
        return False

    def read_side(self, side: int) -> Iterator[BlockRead]:
        packed = self.read_raw_side(what=f"reading side {side}")
        read = sum(1 for capture in self._captures if capture.side == side) + 1
        self._captures.append(Capture(side=side, read=read, data=packed))
        decoded, found = decode_packed(packed)
        self._pulse.extend(findings_of(side, read, found))
        for index, block in enumerate(decoded.blocks):
            yield BlockRead(
                index=index,
                payload=block.payload,
                crc_ok=block.stored_crc == block.computed_crc,
                attempts=1,
                stored_crc=block.stored_crc,
            )

    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        self.write_raw_side(
            encode_write_stream(blocks), what=f"writing side {side}", fill_to=BLANKED_PACKETS
        )


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

    def write_output(self, data: bytes) -> int:
        return self._device.write(data)

    def close(self) -> None:
        self._device.close()


@runtime_checkable
class HidModule(Protocol):
    def device(self) -> HidDevice: ...

    def enumerate(self, vendor_id: int, product_id: int) -> list[dict[str, object]]: ...


def _load_hid() -> HidModule:
    return cast("HidModule", importlib.import_module("hid"))


def _opened(hid: HidModule) -> HidDevice:
    device = hid.device()
    try:
        device.open(VENDOR_ID, PRODUCT_ID)
    except OSError as error:
        message = (
            f"no FDSStick answered at {VENDOR_ID:#06x}:{PRODUCT_ID:#06x}. "
            "Check the USB cable and that no other program holds the device"
        )
        raise HardwareFaultError(message, kind=FaultKind.LINK) from error
    return device


def prime_hid() -> None:
    try:
        hid = _load_hid()
    except ImportError:
        logger.info("hidapi is not installed, so there is no USB layer to start")
        return
    hid.enumerate(VENDOR_ID, PRODUCT_ID)


def open_fdsstick() -> FdsStick:
    try:
        hid = _load_hid()
    except ImportError as error:
        message = (
            "hidapi is not installed, so an FDSStick cannot be opened. "
            "Homebrew installs it with the toolkit: brew reinstall gufranco/tap/fdstoolkit"
        )
        raise HardwareFaultError(message, kind=FaultKind.LINK) from error

    lock = acquire_drive_lock()
    try:
        return FdsStick(HidApiTransport(_opened(hid)), lock=lock)
    except BaseException:
        lock.release()
        raise
