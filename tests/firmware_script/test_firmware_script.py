from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fdsstick_firmware.py"
FLASH_BYTES = 1 << 19
TOP = FLASH_BYTES - 0x10000
UPDATE_AT = 0xFF0000
REGION = 0x2000
PAYLOAD = bytes(range(256)) * 28


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fdsstick_firmware", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def image(version: int = 0x80) -> bytes:
    head = bytes([0xFF, 0xFF, 0x55, 0xAA, 0x2E, version])
    return head + len(PAYLOAD).to_bytes(2, "little") + PAYLOAD


@dataclass
class FakeStick:
    memory: bytearray = field(default_factory=lambda: bytearray(b"\xff" * FLASH_BYTES))
    forgets: bool = False
    chip: bytes = bytes([0x20, 0x80, 0x13])
    stream: bytearray = field(default_factory=bytearray)
    writable: bool = False
    cursor: int = 0
    applied: int = 0
    reports: list[int] = field(default_factory=list[int])

    def _command(self) -> int:
        return self.stream[0] if self.stream else 0

    def _finish(self) -> None:
        command, body = self._command(), bytes(self.stream[1:])
        at = int.from_bytes(body[:3], "big") % FLASH_BYTES
        if command == 0x06:
            self.writable = True
        elif command == 0x20 and self.writable:
            self.memory[at : at + 0x1000] = b"\xff" * 0x1000
            self.writable = False
        elif command == 0x02 and self.writable and not self.forgets:
            for offset, byte in enumerate(body[3:]):
                self.memory[at + offset] &= byte
            self.writable = False
        self.stream.clear()

    def send_feature_report(self, data: bytes) -> int:
        self.reports.append(data[0])
        if data[0] == 0xF1:
            self.applied += 1
            return len(data)
        size, start, hold = data[1], data[2], data[3]
        if start:
            self.stream.clear()
        self.stream += data[4 : 4 + size]
        if self._command() == 0x03 and len(self.stream) >= 4:
            self.cursor = int.from_bytes(self.stream[1:4], "big") % FLASH_BYTES
        if not hold:
            self._finish()
        return len(data)

    def get_feature_report(self, report_id: int, length: int) -> list[int]:
        del length
        if self._command() == 0x9F:
            body = self.chip.ljust(63, b"\0")
        elif self._command() == 0x05:
            body = bytes(63)
        else:
            body = bytes(self.memory[self.cursor : self.cursor + 63]).ljust(63, b"\xff")
            self.cursor += 63
        if report_id == 2:
            self.stream.clear()
        return [report_id, *body]

    def close(self) -> None:
        self.stream.clear()


def quiet(line: str) -> None:
    del line


def test_the_image_is_found_in_a_program_by_its_marker_and_length() -> None:
    script = load_script()

    found = script.blob_in(bytes(4000) + image() + bytes(900))

    assert found == image()
    assert script.version_of(found) == 0x80


def test_a_program_holding_no_image_is_refused() -> None:
    script = load_script()

    with pytest.raises(script.FirmwareError, match="exactly one"):
        script.blob_in(bytes(4000))


def test_a_region_written_through_the_stick_reads_back_the_same() -> None:
    script = load_script()
    stick = FakeStick()
    stick.memory[TOP : TOP + REGION] = bytes(REGION)

    flash = script.checked(script.Flash(stick))
    flash.write(UPDATE_AT, image())

    assert flash.read(UPDATE_AT, len(image())) == image()
    assert set(stick.memory[TOP + len(image()) : TOP + REGION]) == {0xFF}


def test_an_image_is_applied_only_after_it_reads_back_as_written() -> None:
    script = load_script()
    stick = FakeStick()
    saved = bytes(stick.memory[TOP : TOP + REGION])

    wrote = script.install(script.Flash(stick), image(), saved, quiet)

    assert wrote
    assert stick.applied == 1
    assert stick.reports.index(0xF1) == len(stick.reports) - 1


def test_an_image_that_does_not_read_back_is_never_applied() -> None:
    script = load_script()
    stick = FakeStick(forgets=True)
    saved = bytes(stick.memory[TOP : TOP + REGION])

    with pytest.raises(script.FirmwareError, match="did not read back"):
        script.install(script.Flash(stick), image(), saved, quiet)

    assert stick.applied == 0


def test_an_image_already_on_the_stick_is_applied_without_a_write() -> None:
    script = load_script()
    stick = FakeStick()
    stick.memory[TOP : TOP + len(image())] = image()
    saved = bytes(stick.memory[TOP : TOP + REGION])

    wrote = script.install(script.Flash(stick), image(), saved, quiet)

    assert not wrote
    assert 0x20 not in [byte for byte in stick.reports if byte != 0x03]
    assert stick.applied == 1


def test_a_region_that_changed_since_its_backup_stops_everything() -> None:
    script = load_script()
    stick = FakeStick()

    with pytest.raises(script.FirmwareError, match="no longer matches"):
        script.install(script.Flash(stick), image(), bytes(REGION), quiet)

    assert stick.applied == 0


def test_a_flash_chip_this_was_never_run_against_is_refused() -> None:
    script = load_script()
    stick = FakeStick(chip=bytes([0xEF, 0x40, 0x18]))

    with pytest.raises(script.FirmwareError, match="not the 208013"):
        script.checked(script.Flash(stick))
