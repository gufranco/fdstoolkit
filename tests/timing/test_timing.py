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
from fdstoolkit.drive.timing import Nature, TimingReader, classify, measure_timing

SEED = b"timing"
CLOCK_SCALE = 1.5
JITTER = 3
NOMINALS = (NOMINAL_SHORT, NOMINAL_MEDIUM, NOMINAL_LONG)
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


class SideDrive:
    def __init__(self, answer: bytes) -> None:
        self.answer = answer

    def read_raw_side(self, *, what: str) -> bytes:
        del what
        return self.answer


def test_counts_from_a_clean_side_are_pulse_timing() -> None:
    # Arrange
    data = counts_of(packed_side())

    # Act
    result = classify(data)

    # Assert
    assert result is Nature.TIMING


def test_packed_classes_are_not_pulse_timing() -> None:
    # Arrange
    data = packed_side()

    # Act
    result = classify(data)

    # Assert
    assert result is Nature.CLASSES


def test_an_empty_answer_is_nothing() -> None:
    # Arrange
    data = b""

    # Act
    result = classify(data)

    # Assert
    assert result is Nature.NOTHING


def test_counts_that_decode_no_block_are_named_as_such() -> None:
    # Arrange
    expected = Nature.UNDECODED

    # Act
    scattered = bytes(80 + byte % 120 for byte in noise(20000))

    # Assert
    assert classify(scattered) is expected


def test_timing_reports_each_class_at_its_measured_length() -> None:
    # Arrange
    counts = counts_of(packed_side())

    # Act
    timing = measure_timing(counts)

    # Assert
    assert timing.means == pytest.approx(
        tuple(nominal * CLOCK_SCALE for nominal in NOMINALS), abs=1.0
    )
    assert all(0 < spread < JITTER for spread in timing.spreads)
    assert 0 < timing.spread_percent < JITTER


def test_a_wider_jitter_reads_as_a_wider_spread() -> None:
    # Arrange
    tight = measure_timing(counts_of(packed_side(), jitter=1))

    # Act
    loose = measure_timing(counts_of(packed_side(), jitter=6))

    # Assert
    assert loose.spread_percent > tight.spread_percent


def test_the_timing_line_names_every_class_and_the_spread() -> None:
    # Arrange
    timing = measure_timing(counts_of(packed_side()))

    # Act
    line = timing.render()

    # Assert
    assert line.startswith("timing: short ")
    assert "medium" in line
    assert "long" in line
    assert "%, smaller is better; bit rate " in line


def test_a_timing_reader_measures_a_read_that_sends_counts_and_hands_on_classes() -> None:
    # Arrange
    lines: list[str] = []
    reader = TimingReader(SideDrive(counts_of(packed_side())), note=lines.append)

    # Act
    packed = reader.read_raw_side(what="calibration read 1")

    # Assert
    assert unpack_raw03(packed)[: len(unpack_raw03(packed_side()))] == unpack_raw03(packed_side())
    assert lines[0].startswith("timing: short")
    assert len(reader.timings) == 1


def test_a_timing_reader_passes_pulse_classes_on_untouched_and_silent() -> None:
    # Arrange
    lines: list[str] = []
    reader = TimingReader(SideDrive(packed_side()), note=lines.append)

    # Act
    packed = reader.read_raw_side(what="calibration read 1")

    # Assert
    assert packed == packed_side()
    assert lines == []
    assert reader.timings == []


def test_the_timing_line_names_the_bit_rate_against_the_adapter_tolerance() -> None:
    # Arrange
    counts = counts_of(packed_side(), scale=1.0)

    # Act
    timing = measure_timing(counts)

    # Assert
    assert timing.rate_khz == pytest.approx(96.8, abs=0.5)
    assert "bit rate 96." in timing.render()
    assert "inside the ±10% the RAM adapter accepts" in timing.render()


def test_a_rate_far_off_nominal_is_named_outside_the_tolerance() -> None:
    # Arrange
    counts = counts_of(packed_side(), scale=1.25)

    # Act
    timing = measure_timing(counts)

    # Assert
    assert timing.rate_khz < 96.4 * 0.9
    assert "outside the ±10% the RAM adapter accepts" in timing.render()
