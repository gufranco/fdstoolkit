from __future__ import annotations

import pytest

from fdstoolkit.flux.hfe import (
    HEADER_SIZE,
    MAGIC,
    bitcells_to_intervals,
    cell_ns,
    is_hfe,
    read_hfe,
    write_hfe,
)
from fdstoolkit.flux.model import FluxCapture, FluxTrack, Revolution, Source

BIT_RATE_KBPS = 250


def _capture(intervals: tuple[int, ...] = (4_000, 8_000, 4_000)) -> FluxCapture:
    return FluxCapture(
        source=Source.SYNTHETIC,
        tracks=(FluxTrack(index=0, revolutions=(Revolution(intervals=intervals),)),),
    )


def test_a_cell_period_comes_from_the_bit_rate() -> None:
    assert cell_ns(BIT_RATE_KBPS) == 2_000


def test_a_bit_rate_of_zero_is_refused() -> None:
    with pytest.raises(ValueError, match="bit rate must be positive"):
        cell_ns(0)


def test_set_bits_become_intervals_of_whole_cells() -> None:
    result = bitcells_to_intervals(bytes((0b0000_0101,)), cell_period_ns=2_000)

    assert result == (4_000,)


def test_a_track_with_no_transition_yields_nothing() -> None:
    assert bitcells_to_intervals(bytes(4), cell_period_ns=2_000) == ()


def test_a_written_image_is_recognised() -> None:
    assert is_hfe(write_hfe(_capture(), bit_rate_kbps=BIT_RATE_KBPS))
    assert not is_hfe(b"SCP")
    assert not is_hfe(b"")


def test_an_image_round_trips_its_intervals() -> None:
    capture = _capture()

    restored = read_hfe(write_hfe(capture, bit_rate_kbps=BIT_RATE_KBPS))

    assert restored.source is Source.HFE
    assert restored.track(0).intervals() == (4_000, 8_000, 4_000)


def test_two_tracks_survive_the_round_trip() -> None:
    capture = FluxCapture(
        source=Source.SYNTHETIC,
        tracks=(
            FluxTrack(index=0, revolutions=(Revolution(intervals=(4_000, 4_000)),)),
            FluxTrack(index=1, revolutions=(Revolution(intervals=(6_000, 4_000)),)),
        ),
    )

    restored = read_hfe(write_hfe(capture, bit_rate_kbps=BIT_RATE_KBPS))

    assert restored.track_count == 2
    assert restored.track(1).intervals() == (6_000, 4_000)


def test_a_file_without_the_signature_is_refused() -> None:
    with pytest.raises(ValueError, match="not an HxC image"):
        read_hfe(b"NOTHXC01" + bytes(HEADER_SIZE))


def test_a_file_shorter_than_its_header_is_refused() -> None:
    with pytest.raises(ValueError, match="too short"):
        read_hfe(MAGIC + bytes(8))


def test_an_image_declaring_no_track_is_refused() -> None:
    data = bytearray(write_hfe(_capture(), bit_rate_kbps=BIT_RATE_KBPS))
    data[0x09] = 0
    with pytest.raises(ValueError, match="names no track"):
        read_hfe(bytes(data))


def test_a_lookup_table_running_past_the_file_is_refused() -> None:
    data = bytearray(write_hfe(_capture(), bit_rate_kbps=BIT_RATE_KBPS))
    data[0x12] = 0xFF
    data[0x13] = 0xFF
    with pytest.raises(ValueError, match="past the end"):
        read_hfe(bytes(data))


def test_a_zero_bit_rate_in_the_header_is_refused() -> None:
    data = bytearray(write_hfe(_capture(), bit_rate_kbps=BIT_RATE_KBPS))
    data[0x0C] = 0
    data[0x0D] = 0
    with pytest.raises(ValueError, match="bit rate must be positive"):
        read_hfe(bytes(data))
