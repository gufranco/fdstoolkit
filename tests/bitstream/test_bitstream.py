from __future__ import annotations

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.qd import decode as decode_qd
from fdstoolkit.codecs.qd import encode as encode_qd
from fdstoolkit.core.bitstream import (
    GAP_BITS,
    GAP_TERMINATOR,
    LEAD_IN_BITS,
    emulated_side_size,
    encode_side_bitstream,
    fits_emulation_buffer,
    gap_length,
)


def sample_side(sides: int = 1):  # noqa: ANN201
    disk, _ = decode(blank_image(sides=sides, headered=False, formatted=True, game_name="SMB"))
    return disk.sides[0]


def test_a_gap_is_its_bit_count_rounded_down_to_whole_bytes() -> None:
    assert gap_length(LEAD_IN_BITS) == 3537
    assert gap_length(GAP_BITS) == 122


def test_a_bitstream_opens_with_the_lead_in_and_its_terminator() -> None:
    stream = encode_side_bitstream(sample_side())

    assert stream[: gap_length(LEAD_IN_BITS)] == bytes(gap_length(LEAD_IN_BITS))
    assert stream[gap_length(LEAD_IN_BITS)] == GAP_TERMINATOR


def test_every_block_is_followed_by_its_crc() -> None:
    side = sample_side()
    stream = encode_side_bitstream(side)
    start = gap_length(LEAD_IN_BITS) + 1
    first = side.blocks[0]

    assert stream[start : start + first.size] == first.payload
    stored = stream[start + first.size] | (stream[start + first.size + 1] << 8)
    assert stored == first.computed_crc


def test_blocks_are_separated_by_a_gap_and_a_terminator() -> None:
    side = sample_side()
    stream = encode_side_bitstream(side)
    start = gap_length(LEAD_IN_BITS) + 1 + side.blocks[0].size + 2

    assert stream[start : start + gap_length(GAP_BITS)] == bytes(gap_length(GAP_BITS))
    assert stream[start + gap_length(GAP_BITS)] == GAP_TERMINATOR


def test_the_emulated_size_matches_the_stream_it_describes() -> None:
    side = sample_side()

    assert emulated_side_size(side) == len(encode_side_bitstream(side))


def test_a_side_with_more_files_needs_more_room() -> None:
    small = sample_side()
    stream = encode_side_bitstream(small)

    assert len(stream) > gap_length(LEAD_IN_BITS)
    assert emulated_side_size(small) > small.content_size


def test_an_unformatted_side_carries_only_the_lead_in() -> None:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=False))

    stream = encode_side_bitstream(disk.sides[0])

    assert stream == bytes(gap_length(LEAD_IN_BITS)) + bytes([GAP_TERMINATOR])


def test_a_stored_crc_is_preserved_rather_than_recomputed() -> None:
    as_qd, _ = encode_qd(decode(blank_image(sides=1, headered=False, formatted=True))[0])
    from_qd, _ = decode_qd(as_qd)
    side = from_qd.sides[0]

    stream = encode_side_bitstream(side)
    start = gap_length(LEAD_IN_BITS) + 1 + side.blocks[0].size
    stored = stream[start] | (stream[start + 1] << 8)

    assert stored == side.blocks[0].stored_crc


def test_the_gap_constants_are_the_documented_ones() -> None:
    assert LEAD_IN_BITS == 28300
    assert GAP_BITS == 976
    assert GAP_TERMINATOR == 0x80


def test_a_negative_gap_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        gap_length(-1)


def test_a_side_that_fits_the_emulation_buffer_is_reported() -> None:
    assert fits_emulation_buffer(sample_side())
