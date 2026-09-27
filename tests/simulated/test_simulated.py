from __future__ import annotations

from capture_fixture import disk_with_a_file, read_of, short_gapped
from counting_drive import DriveModel, drive_counts
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.raw import NOMINAL_SHORT, SHORTEST_GAP_BITS, pack_raw03, quantise
from fdstoolkit.core.disk import Side
from fdstoolkit.drive.captures import Capture
from fdstoolkit.drive.monitor import NOISY_READ, Calibration, Mode, sample
from fdstoolkit.drive.pulse import captured_findings, settled
from fdstoolkit.drive.timing import (
    CAPTURE_CLOCK_KHZ,
    measure_timing,
)

SETTINGS = settings(max_examples=25, suppress_health_check=[HealthCheck.too_slow], deadline=None)
RATE_ERROR = 0.01
LONGEST_LEAD_IN = 30000


def blank_side() -> Side:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="SIM"))
    return disk.sides[0]


def fixed_classes(counts: bytes) -> bytes:
    return pack_raw03(quantise(counts))


@SETTINGS
@given(
    speed=st.floats(min_value=0.8, max_value=1.2),
    jitter=st.integers(min_value=0, max_value=3),
    seed=st.integers(min_value=0, max_value=2**16),
)
def test_the_bit_rate_meter_reads_the_speed_the_drive_runs_at(
    speed: float, jitter: int, seed: int
) -> None:
    counts = drive_counts(blank_side(), DriveModel(speed=speed, jitter=jitter, seed=seed))

    timing = measure_timing(counts)

    expected = CAPTURE_CLOCK_KHZ * speed / NOMINAL_SHORT
    assert abs(timing.rate_khz - expected) / expected < RATE_ERROR


@SETTINGS
@given(speed=st.floats(min_value=0.93, max_value=1.06), seed=st.integers(min_value=0, max_value=99))
def test_a_drive_well_inside_the_tolerance_is_named_inside(speed: float, seed: int) -> None:
    counts = drive_counts(blank_side(), DriveModel(speed=speed, seed=seed))

    timing = measure_timing(counts)

    assert timing.rate_in_tolerance


@SETTINGS
@given(
    speed=st.one_of(
        st.floats(min_value=0.8, max_value=0.86), st.floats(min_value=1.13, max_value=1.2)
    ),
    seed=st.integers(min_value=0, max_value=99),
)
def test_a_drive_well_outside_the_tolerance_is_named_outside(speed: float, seed: int) -> None:
    counts = drive_counts(blank_side(), DriveModel(speed=speed, seed=seed))

    timing = measure_timing(counts)

    assert not timing.rate_in_tolerance


@SETTINGS
@given(
    lead_in=st.integers(min_value=SHORTEST_GAP_BITS * 60, max_value=LONGEST_LEAD_IN),
    seed=st.integers(min_value=0, max_value=99),
)
def test_the_lead_in_reported_is_the_lead_in_the_disk_carries(lead_in: int, seed: int) -> None:
    side = blank_side()
    counts = drive_counts(side, DriveModel(lead_in=lead_in, seed=seed))

    found = sample(fixed_classes(counts), side)

    assert found.lead_in == lead_in


@SETTINGS
@given(
    strays=st.integers(min_value=16, max_value=60),
    seed=st.integers(min_value=0, max_value=99),
)
def test_a_read_full_of_stray_pulses_names_the_read_line(strays: int, seed: int) -> None:
    side = blank_side()
    counts = drive_counts(side, DriveModel(strays=strays, seed=seed))

    headline = Calibration(mode=Mode.SPEED, samples=(sample(fixed_classes(counts), side),)).headline

    assert headline.endswith(NOISY_READ)


@SETTINGS
@given(
    speed=st.floats(min_value=0.9, max_value=1.1),
    seed=st.integers(min_value=0, max_value=99),
)
def test_a_drive_that_only_runs_off_speed_is_not_called_noisy(speed: float, seed: int) -> None:
    side = blank_side()
    counts = drive_counts(side, DriveModel(speed=speed, seed=seed))

    headline = Calibration(mode=Mode.SPEED, samples=(sample(fixed_classes(counts), side),)).headline

    assert NOISY_READ not in headline


@SETTINGS
@given(
    reads=st.integers(min_value=2, max_value=5),
    flawed=st.data(),
)
def test_a_short_gap_counts_against_the_disk_only_when_every_read_shows_it(
    reads: int, flawed: st.DataObject
) -> None:
    disk = disk_with_a_file()
    shown_by = flawed.draw(st.sets(st.integers(min_value=1, max_value=reads), min_size=1))
    captures = [
        short_gapped(disk, read)
        if read in shown_by
        else Capture(side=0, read=read, data=read_of(disk, None))
        for read in range(1, reads + 1)
    ]

    kept = settled(captured_findings(captures), captures)

    assert bool(kept) == (len(shown_by) == reads)
