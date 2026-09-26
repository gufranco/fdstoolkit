from __future__ import annotations

import hashlib

import pytest

from fdstoolkit.build.calibration import calibration_disk
from fdstoolkit.codecs.raw import (
    NOMINAL_LONG,
    NOMINAL_MEDIUM,
    NOMINAL_SHORT,
    encode_raw03,
    unpack_raw03,
)
from fdstoolkit.drive.timing import (
    NO_TIMING,
    Nature,
    ProbeResult,
    TimingReader,
    classify,
    measure_timing,
    probe,
)
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError

SEED = b"timing"
CLOCK_SCALE = 1.5
JITTER = 3
NOMINALS = (NOMINAL_SHORT, NOMINAL_MEDIUM, NOMINAL_LONG)
TIMING_MODE = 3
LEAD_OUT = 4000


def packed_side() -> bytes:
    return encode_raw03(calibration_disk(1), side=0)


def noise(size: int) -> bytes:
    return hashlib.shake_256(SEED).digest(size)


def counts_of(packed: bytes, *, scale: float = CLOCK_SCALE, jitter: int = JITTER) -> bytes:
    classes = unpack_raw03(packed) + bytes(LEAD_OUT)
    offsets = noise(len(classes))
    return bytes(
        max(1, min(255, round(NOMINALS[value] * scale) + offset % (2 * jitter + 1) - jitter))
        for value, offset in zip(classes, offsets, strict=True)
    )


class ModeDrive:
    def __init__(self, answers: dict[int, bytes], *, fail_on: int | None = None) -> None:
        self.answers = answers
        self.fail_on = fail_on
        self.modes: list[int] = []

    def read_raw_side(self, *, what: str, mode: int = 0) -> bytes:
        del what
        self.modes.append(mode)
        if mode == self.fail_on:
            message = "the device stopped answering"
            raise HardwareFaultError(message, kind=FaultKind.LINK)
        return self.answers.get(mode, self.answers[0])


def test_counts_from_a_clean_side_are_pulse_timing() -> None:
    assert classify(counts_of(packed_side())) is Nature.TIMING


def test_packed_classes_are_not_pulse_timing() -> None:
    assert classify(packed_side()) is Nature.CLASSES


def test_an_empty_answer_is_nothing() -> None:
    assert classify(b"") is Nature.NOTHING


def test_counts_that_decode_no_block_are_named_as_such() -> None:
    scattered = bytes(80 + byte % 120 for byte in noise(20000))

    assert classify(scattered) is Nature.UNDECODED


def test_timing_reports_each_class_at_its_measured_length() -> None:
    timing = measure_timing(counts_of(packed_side()))

    assert timing.means == pytest.approx(
        tuple(nominal * CLOCK_SCALE for nominal in NOMINALS), abs=1.0
    )
    assert all(0 < spread < JITTER for spread in timing.spreads)
    assert 0 < timing.spread_percent < JITTER


def test_a_wider_jitter_reads_as_a_wider_spread() -> None:
    tight = measure_timing(counts_of(packed_side(), jitter=1))
    loose = measure_timing(counts_of(packed_side(), jitter=6))

    assert loose.spread_percent > tight.spread_percent


def test_the_timing_line_names_every_class_and_the_spread() -> None:
    line = measure_timing(counts_of(packed_side())).render()

    assert line.startswith("timing: short ")
    assert "medium" in line
    assert "long" in line
    assert line.endswith("%, smaller is better")


def test_the_probe_stops_at_the_first_mode_that_returns_timing() -> None:
    drive = ModeDrive({0: packed_side(), TIMING_MODE: counts_of(packed_side())})

    found = probe(drive, modes=(2, TIMING_MODE, 4))

    assert [result.nature for result in found.results] == [Nature.CLASSES, Nature.TIMING]
    assert found.timing_mode == TIMING_MODE
    assert found.changed_by is None


def test_a_probe_that_finds_no_timing_says_so() -> None:
    drive = ModeDrive({0: packed_side()})

    found = probe(drive, modes=(2, 3))

    assert found.timing_mode is None
    assert found.verdict == NO_TIMING


def test_a_mode_that_changes_the_disk_stops_the_probe() -> None:
    class ErasingDrive(ModeDrive):
        def read_raw_side(self, *, what: str, mode: int = 0) -> bytes:
            data = super().read_raw_side(what=what, mode=mode)
            if mode == 2:
                self.answers[0] = bytes(len(self.answers[0]))
            return data

    drive = ErasingDrive({0: packed_side()})

    found = probe(drive, modes=(2, 3))

    assert found.changed_by == 2
    assert drive.modes == [0, 2, 0]
    assert "mode 0x02 changed the disk" in found.verdict


def test_a_fault_ends_the_probe_and_is_reported() -> None:
    drive = ModeDrive({0: packed_side()}, fail_on=3)

    found = probe(drive, modes=(2, 3, 4))

    assert found.results[-1] == ProbeResult(
        mode=3, nature=Nature.FAULT, detail="the device stopped answering"
    )
    assert 4 not in drive.modes
    assert found.verdict == (
        "the probe stopped on a fault before it found pulse timing: the device stopped answering"
    )


def test_a_timing_reader_hands_the_calibration_pulse_classes() -> None:
    lines: list[str] = []
    drive = ModeDrive({0: packed_side(), TIMING_MODE: counts_of(packed_side())})
    reader = TimingReader(drive, mode=TIMING_MODE, note=lines.append)

    packed = reader.read_raw_side(what="calibration read 1")

    assert unpack_raw03(packed)[: len(unpack_raw03(packed_side()))] == unpack_raw03(packed_side())
    assert lines[0].startswith("timing: short")
    assert len(reader.timings) == 1


def test_a_timing_reader_falls_back_to_classes_and_warns() -> None:
    lines: list[str] = []
    drive = ModeDrive({0: packed_side()})
    reader = TimingReader(drive, mode=TIMING_MODE, note=lines.append)

    packed = reader.read_raw_side(what="calibration read 1")

    assert packed == packed_side()
    assert lines == [
        (
            "calibration read 1: mode 0x03 returned pulse classes only, so this read is "
            "judged from classes and shows no timing"
        )
    ]
    assert reader.timings == []
