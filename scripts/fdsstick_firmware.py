"""Read an FDSStick's firmware image out of loopy's Windows programs and put it on a stick.

The toolkit's driver never touches the stick's SPI flash. This script is the one place
that does, and it stays outside the library on purpose.

    fdsstick_firmware.py extract FDSStick_readRaw.exe readraw_2.80.bin
    fdsstick_firmware.py backup  backup_dir
    fdsstick_firmware.py flash   readraw_2.80.bin backup_dir

The sequence follows the update thread of FDSStick_readRaw.exe and FDSStick_20160926.exe:
save the top of the SPI flash, write the image there, send report 0xF1, wait for the stick
to come back, put the saved bytes back. It adds one step neither program has: the image is
read back and compared before 0xF1 is sent.

Run against one stick, flash id 20 80 13, going from firmware 3.12 to 2.80: the identify
query, the reads, 0xF1 and the restart. The erase and the page program have not run against
a device, because that stick already held the image; they are tested against a stand-in.
Take the disk out of the drive first.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

VENDOR_ID: Final = 0x16D0
PRODUCT_ID: Final = 0x0AAA
REPORT: Final = 64
CHUNK_OUT: Final = 0x3C
UPDATE_AT: Final = 0xFF0000
SECTOR: Final = 0x1000
PAGE: Final = 0x100
KNOWN_FLASH: Final = bytes([0x20, 0x80, 0x13])
FLASH_BYTES: Final = 1 << 0x13
MARKER: Final = bytes([0xFF, 0xFF, 0x55, 0xAA])
HEADER: Final = 8
VERSION_AT: Final = 5
SPI: Final = 0x03
HOLD: Final = 0x01
RELEASE: Final = 0x02
APPLY: Final = 0xF1
WRITE_ENABLE: Final = 0x06
STATUS: Final = 0x05
READ: Final = 0x03
PROGRAM: Final = 0x02
ERASE_SECTOR: Final = 0x20
IDENTIFY: Final = 0x9F
BUSY: Final = 0x01
ERASE_MS: Final = 800
PROGRAM_MS: Final = 50
RETURN_TRIES: Final = 40
RETURN_PAUSE_S: Final = 0.5
SETTLE_TRIES: Final = 4


class FirmwareError(Exception):
    pass


class Device(Protocol):
    def send_feature_report(self, data: bytes) -> int: ...

    def get_feature_report(self, report_id: int, length: int) -> list[int]: ...

    def close(self) -> None: ...


def blob_in(program: bytes) -> bytes:
    start = program.find(MARKER)
    if start < 0 or program.find(MARKER, start + 1) >= 0:
        message = "expected exactly one firmware image in this program"
        raise FirmwareError(message)
    size = HEADER + int.from_bytes(program[start + 6 : start + HEADER], "little")
    blob = program[start : start + size]
    if len(blob) != size or size > 2 * SECTOR:
        message = f"the image header declares {size} bytes, which this program does not hold"
        raise FirmwareError(message)
    return blob


def version_of(blob: bytes) -> int:
    if blob[: len(MARKER)] != MARKER or blob_in(blob) != blob:
        message = "this file is not a firmware image taken with extract"
        raise FirmwareError(message)
    return blob[VERSION_AT]


class Flash:
    def __init__(self, device: Device, *, now: Callable[[], float] = time.monotonic) -> None:
        self._device = device
        self._now = now

    def _send(self, data: bytes, *, start: bool, hold: bool) -> None:
        packet = bytes([SPI, len(data), int(start), int(hold)]) + data
        self._device.send_feature_report(packet.ljust(REPORT, b"\0"))

    def _take(self, *, hold: bool) -> bytes:
        answer = bytes(self._device.get_feature_report(HOLD if hold else RELEASE, REPORT + 1))
        return answer[1:REPORT]

    def identify(self) -> bytes:
        self._send(bytes([IDENTIFY]), start=True, hold=True)
        return self._take(hold=False)[: len(KNOWN_FLASH)]

    def read(self, at: int, size: int) -> bytes:
        self._send(bytes([READ]) + _address(at), start=True, hold=True)
        out = bytearray()
        while len(out) < size:
            out += self._take(hold=size - len(out) >= REPORT)
        return bytes(out[:size])

    def _settle(self, limit_ms: int) -> None:
        self._send(bytes([STATUS]), start=True, hold=True)
        started = self._now()
        busy = True
        while busy and (self._now() - started) * 1000 <= limit_ms:
            busy = bool(self._take(hold=True)[0] & BUSY)
        self._send(b"", start=False, hold=False)
        if busy:
            message = f"the flash was still busy after {limit_ms} ms"
            raise FirmwareError(message)

    def _erase(self, at: int) -> None:
        self._send(bytes([WRITE_ENABLE]), start=True, hold=False)
        self._send(bytes([ERASE_SECTOR]) + _address(at), start=True, hold=False)
        self._settle(ERASE_MS)

    def _program(self, at: int, data: bytes) -> None:
        self._send(bytes([WRITE_ENABLE]), start=True, hold=False)
        stream = bytes([PROGRAM]) + _address(at) + data
        for offset in range(0, len(stream), CHUNK_OUT):
            chunk = stream[offset : offset + CHUNK_OUT]
            self._send(chunk, start=offset == 0, hold=offset + CHUNK_OUT < len(stream))
        self._settle(PROGRAM_MS)

    def write(self, at: int, data: bytes) -> None:
        done = 0
        while done < len(data):
            here = at + done
            if done == 0 or here % SECTOR == 0:
                self._erase(here)
            size = min(PAGE - here % PAGE, len(data) - done)
            self._program(here, data[done : done + size])
            done += size

    def apply(self) -> None:
        self._device.send_feature_report(bytes([APPLY, 0, 0, 0, STATUS]).ljust(REPORT, b"\0"))


def _address(at: int) -> bytes:
    return (at & 0xFFFFFF).to_bytes(3, "big")


def checked(flash: Flash) -> Flash:
    found = flash.identify()
    if found != KNOWN_FLASH:
        message = f"flash id {found.hex()} is not the {KNOWN_FLASH.hex()} this was run against"
        raise FirmwareError(message)
    return flash


def install(flash: Flash, blob: bytes, saved: bytes, say: Callable[[str], None]) -> bool:
    if flash.read(UPDATE_AT, len(saved)) != saved:
        message = "the update region no longer matches its backup, so nothing was written"
        raise FirmwareError(message)
    present = saved[: len(blob)] == blob
    if present:
        say("the image is already on the stick, so nothing is written")
    else:
        flash.write(UPDATE_AT, blob)
    if flash.read(UPDATE_AT, len(blob)) != blob:
        flash.write(UPDATE_AT, saved)
        message = "the image did not read back as written; the region is restored, nothing applied"
        raise FirmwareError(message)
    say("the image reads back as written, applying it")
    flash.apply()
    return not present


def _hid() -> object:
    return importlib.import_module("hid")


def _release() -> int | None:
    found = _hid().enumerate(VENDOR_ID, PRODUCT_ID)  # type: ignore[attr-defined]
    return found[0]["release_number"] if found else None


def _opened() -> Device:
    device = _hid().device()  # type: ignore[attr-defined]
    device.open(VENDOR_ID, PRODUCT_ID)
    return device


def _returned() -> int:
    seen = 0
    for _ in range(RETURN_TRIES):
        time.sleep(RETURN_PAUSE_S)
        release = _release()
        seen = seen + 1 if release is not None else 0
        if release is not None and seen >= SETTLE_TRIES:
            return release
    message = "the stick did not come back. Unplug it and plug it back in, then run backup"
    raise FirmwareError(message)


def _say(line: str) -> None:
    sys.stdout.write(f"{line}\n")


def extract(program: Path, target: Path) -> None:
    blob = blob_in(program.read_bytes())
    target.write_bytes(blob)
    _say(f"wrote {target}: {len(blob)} bytes, firmware x.{version_of(blob):02x}")


def backup(folder: Path) -> None:
    device = _opened()
    try:
        flash = checked(Flash(device))
        first = flash.read(0, FLASH_BYTES)
        second = flash.read(0, FLASH_BYTES)
        region = flash.read(UPDATE_AT, 2 * SECTOR)
    finally:
        device.close()
    if first != second:
        message = "two reads of the flash disagree, so nothing was saved"
        raise FirmwareError(message)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "spi_flash.bin").write_bytes(first)
    (folder / "update_region.bin").write_bytes(region)
    _say(f"firmware {_release() or 0:#06x}, flash {len(first)} bytes saved in {folder}")


def flash_image(image: Path, folder: Path) -> None:
    blob = image.read_bytes()
    wanted = version_of(blob)
    saved = (folder / "update_region.bin").read_bytes()
    device = _opened()
    try:
        wrote = install(checked(Flash(device)), blob, saved, _say)
    finally:
        device.close()
    release = _returned()
    if wrote:
        device = _opened()
        try:
            checked(Flash(device)).write(UPDATE_AT, saved)
        finally:
            device.close()
    verdict = "as wanted" if release & 0xFF == wanted else f"not the x.{wanted:02x} wanted"
    _say(f"the stick reports firmware {release >> 8:x}.{release & 0xFF:02x}, {verdict}")


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    taken = commands.add_parser("extract", help="take the firmware image out of a Windows program")
    taken.add_argument("program", type=Path)
    taken.add_argument("image", type=Path)
    kept = commands.add_parser("backup", help="save the stick's whole SPI flash")
    kept.add_argument("folder", type=Path)
    put = commands.add_parser("flash", help="write an image, verify it, apply it")
    put.add_argument("image", type=Path)
    put.add_argument("folder", type=Path, help="the folder backup wrote")
    chosen = parser.parse_args(arguments)
    try:
        if chosen.command == "extract":
            extract(chosen.program, chosen.image)
        elif chosen.command == "backup":
            backup(chosen.folder)
        else:
            flash_image(chosen.image, chosen.folder)
    except (FirmwareError, OSError) as error:
        sys.stderr.write(f"{error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
