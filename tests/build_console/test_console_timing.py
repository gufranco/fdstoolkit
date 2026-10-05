from __future__ import annotations

import hashlib
import importlib.util
import math
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest
from cpu6502 import CARRY, Cpu

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_console.py"
PROGRAM_START = 0x6000
DISK_STATUS = 0x4030
DATA_READ = 0x4031
BYTE_READY = 0x02
REQUIRE_CC65 = os.environ.get("FDSTOOLKIT_REQUIRE_CC65") == "1"

pytestmark = pytest.mark.skipif(
    shutil.which("ca65") is None and not REQUIRE_CC65,
    reason="cc65 is not installed; CI sets FDSTOOLKIT_REQUIRE_CC65=1 so it never skips there",
)


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_console", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass
class Drive:
    period: float
    start: float
    delivered: int = 0
    pending: bool = False

    def __call__(self, address: int, cycle: int) -> int:
        while self.start + self.delivered * self.period <= cycle:
            self.delivered += 1
            self.pending = True
        if address == DISK_STATUS:
            ready = BYTE_READY if self.pending else 0
            self.pending = False
            return ready
        if address == DATA_READ:
            self.pending = False
            return 0x55
        return 0


@dataclass(frozen=True)
class Program:
    image: bytes
    labels: dict[str, int]


@pytest.fixture(scope="module", name="program")
def program_fixture(tmp_path_factory: pytest.TempPathFactory) -> Program:
    build_dir = tmp_path_factory.mktemp("console")
    load_script().build(build_dir)
    labels: dict[str, int] = {}
    for line in (build_dir / "labels.txt").read_text(encoding="utf-8").splitlines():
        _, address, name = line.split()
        labels[name.lstrip(".")] = int(address, 16)
    return Program(image=(build_dir / "console-main.bin").read_bytes(), labels=labels)


def word(cpu: Cpu, address: int) -> int:
    return cpu.memory[address] | cpu.memory[address + 1] << 8


def time_bytes(program: Program, *, period: float, count: int) -> Cpu:
    cpu = Cpu()
    cpu.load(PROGRAM_START, program.image)
    labels = program.labels
    cpu.memory[labels["timed_blocks"]] = 1
    cpu.memory[labels["remaining"]] = count & 0xFF
    cpu.memory[labels["remaining"] + 1] = count >> 8
    cpu.read_hook = Drive(period=period, start=0.0)
    cpu.cycles = 10
    cpu.call(labels["byte_arrived"])
    cpu.call(labels["compute_speed"])
    return cpu


@pytest.mark.parametrize("period", [135.03, 148.5289, 150.03, 165.03])
def test_the_measured_cycles_per_byte_match_the_drive(program: Program, period: float) -> None:
    cpu = time_bytes(program, period=period, count=4000)

    measured = word(cpu, program.labels["cycles_x100"])

    assert abs(measured - period * 100) <= 1


def test_a_long_side_exercises_every_counter_carry(program: Program) -> None:
    cpu = time_bytes(program, period=165.03, count=60000)

    measured = word(cpu, program.labels["cycles_x100"])

    assert cpu.memory[program.labels["iterations"] + 2] > 0
    assert abs(measured - 16503) <= 1


def test_random_speeds_across_the_coarse_band_are_measured(program: Program) -> None:
    periods = [135.0 + 30.0 * byte / 255 for byte in hashlib.shake_256(b"speeds").digest(5)]

    measured = [
        word(time_bytes(program, period=p, count=2000), program.labels["cycles_x100"])
        for p in periods
    ]

    assert all(abs(m - p * 100) <= 2 for m, p in zip(measured, periods, strict=True))


def test_the_speed_ratio_is_the_nominal_over_the_measurement(program: Program) -> None:
    cpu = time_bytes(program, period=150.03, count=4000)

    cycles = word(cpu, program.labels["cycles_x100"])

    assert word(cpu, program.labels["speed_x10000"]) == math.floor(148_528_880 / cycles)


def test_nothing_timed_is_reported_without_a_result(program: Program) -> None:
    cpu = Cpu()
    cpu.load(PROGRAM_START, program.image)
    cpu.memory[program.labels["timed_bytes"]] = 3
    cpu.memory[program.labels["timed_blocks"]] = 3

    cpu.call(program.labels["compute_speed"])

    assert cpu.status & CARRY
