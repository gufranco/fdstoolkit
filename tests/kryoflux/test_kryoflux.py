from __future__ import annotations

import pytest

from fdstoolkit.flux.kryoflux import (
    OOB,
    OOB_EOF,
    OOB_INDEX,
    OOB_STREAM_END,
    SAMPLE_CLOCK_HZ,
    is_kryoflux,
    read_stream,
    ticks_to_ns,
)
from fdstoolkit.flux.model import Source


def _flux1(value: int) -> bytes:
    return bytes((value,))


def _flux2(value: int) -> bytes:
    return bytes((value >> 8, value & 0xFF))


def _flux3(value: int) -> bytes:
    return bytes((0x0C, value >> 8, value & 0xFF))


def _oob(kind: int, payload: bytes) -> bytes:
    return bytes((OOB, kind)) + len(payload).to_bytes(2, "little") + payload


def _index(position: int) -> bytes:
    return _oob(
        OOB_INDEX,
        position.to_bytes(4, "little") + bytes(4) + bytes(4),
    )


EOF_BLOCK = bytes((OOB, OOB_EOF)) + (0x0D0D).to_bytes(2, "little")


def test_ticks_convert_to_nanoseconds_against_the_sample_clock() -> None:
    assert ticks_to_ns(round(SAMPLE_CLOCK_HZ)) == pytest.approx(1_000_000_000, rel=1e-6)


def test_a_stream_starting_with_an_out_of_band_block_is_recognised() -> None:
    assert is_kryoflux(_oob(0x04, b"name=value\0"))
    assert not is_kryoflux(b"SCP")
    assert not is_kryoflux(b"")


def test_a_one_byte_cell_carries_its_own_value() -> None:
    capture = read_stream(_flux1(0x40) + _flux1(0x50) + EOF_BLOCK)

    assert capture.source is Source.KRYOFLUX
    assert capture.track(0).intervals() == (ticks_to_ns(0x40), ticks_to_ns(0x50))


def test_a_two_byte_cell_carries_a_value_below_the_one_byte_floor() -> None:
    capture = read_stream(_flux2(0x0300) + EOF_BLOCK)

    assert capture.track(0).intervals() == (ticks_to_ns(0x0300),)


def test_a_three_byte_cell_carries_a_large_value() -> None:
    capture = read_stream(_flux3(0x9000) + EOF_BLOCK)

    assert capture.track(0).intervals() == (ticks_to_ns(0x9000),)


def test_an_overflow_cell_adds_a_full_window_to_the_next_value() -> None:
    capture = read_stream(bytes((0x0B,)) + _flux1(0x40) + EOF_BLOCK)

    assert capture.track(0).intervals() == (ticks_to_ns(0x10000 + 0x40),)


def test_overflow_cells_accumulate() -> None:
    capture = read_stream(bytes((0x0B, 0x0B)) + _flux1(0x40) + EOF_BLOCK)

    assert capture.track(0).intervals() == (ticks_to_ns(0x20000 + 0x40),)


def test_padding_cells_are_skipped_with_their_payload() -> None:
    stream = bytes((0x08,)) + bytes((0x09, 0xFF)) + bytes((0x0A, 0xFF, 0xFF))
    capture = read_stream(stream + _flux1(0x40) + EOF_BLOCK)

    assert capture.track(0).intervals() == (ticks_to_ns(0x40),)


def test_an_index_block_starts_a_new_revolution() -> None:
    stream = _flux1(0x40) + _index(2) + _flux1(0x50) + _flux1(0x60) + EOF_BLOCK

    capture = read_stream(stream)

    assert capture.track(0).revolution_count == 2
    assert capture.track(0).intervals(0) == (ticks_to_ns(0x40),)
    assert capture.track(0).intervals(1) == (ticks_to_ns(0x50), ticks_to_ns(0x60))


def test_an_index_at_the_very_start_does_not_open_an_empty_revolution() -> None:
    capture = read_stream(_index(0) + _flux1(0x40) + EOF_BLOCK)

    assert capture.track(0).revolution_count == 1


def test_a_stream_end_block_is_read_without_ending_the_parse() -> None:
    stream = _oob(OOB_STREAM_END, bytes(8)) + _flux1(0x40) + EOF_BLOCK

    assert read_stream(stream).track(0).intervals() == (ticks_to_ns(0x40),)


def test_parsing_stops_at_the_end_marker() -> None:
    capture = read_stream(_flux1(0x40) + EOF_BLOCK + _flux1(0x7F) * 200)

    assert capture.track(0).intervals() == (ticks_to_ns(0x40),)


def test_a_stream_with_no_cell_is_refused() -> None:
    with pytest.raises(ValueError, match="no flux cell"):
        read_stream(EOF_BLOCK)


def test_a_truncated_cell_at_the_end_is_ignored() -> None:
    capture = read_stream(_flux1(0x40) + bytes((0x0C, 0x90)))

    assert capture.track(0).intervals() == (ticks_to_ns(0x40),)


def test_the_track_index_can_be_named() -> None:
    capture = read_stream(_flux1(0x40) + EOF_BLOCK, track=12)

    assert capture.track(12).index == 12
