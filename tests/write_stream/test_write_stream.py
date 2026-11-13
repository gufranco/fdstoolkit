from __future__ import annotations

import pytest

from fdstoolkit.build.calibration import calibration_disk
from fdstoolkit.codecs.raw import (
    WRITE_FILL,
    WRITE_GAP_BYTES,
    WRITE_HEADER,
    WRITE_LEAD_IN_BYTES,
    WRITE_PACKET_BYTES,
    WRITE_TAIL_GAP_BYTES,
    PackOrder,
    decode_write_stream,
    encode_write_block,
    encode_write_stream,
    unpack_in,
    unpack_raw03,
)
from fdstoolkit.core.crc import block_crc, encode_crc

GAP_BYTE = 0xAA
MARKER = 0x80
FACTORY_FILL = bytes([0xD7, 0x75, 0x5D])
ZERO_THEN_ONE = 3
ONE = 1


def tail_of(stream: bytes, payloads: list[bytes]) -> bytes:
    blocks = sum(2 * len(framed(payload)) for payload in payloads)
    gaps = WRITE_GAP_BYTES * (len(payloads) - 1)
    return stream[len(WRITE_HEADER) + WRITE_LEAD_IN_BYTES + blocks + gaps :]


def framed(payload: bytes) -> bytes:
    return bytes([MARKER]) + payload + encode_crc(block_crc(payload))


def test_the_marker_opens_a_block_with_the_gap_end_pattern() -> None:
    values = encode_write_block(framed(bytes([0x02, 0x00])))

    assert values[:4] == bytes([1, 2, 2, 2])


def test_every_byte_becomes_eight_values_in_the_write_alphabet() -> None:
    block = framed(bytes(range(1, 40)))

    values = encode_write_block(block)

    assert len(values) == 8 * len(block)
    assert set(values) <= {1, 2, 3}


def test_a_zero_bit_before_a_one_bit_is_a_long_value() -> None:
    values = encode_write_block(bytes([0b01000000, 0x00]))

    assert values[:2] == bytes([3, 1])


def test_the_low_nibble_comes_from_the_next_byte() -> None:
    values = encode_write_block(bytes([0x00, 0x0F]))

    assert values[4:8] == bytes([1, 1, 1, 1])


def test_a_side_opens_with_the_header_and_the_lead_in() -> None:
    stream = encode_write_stream([bytes([0x02, 0x00])])

    assert stream[:3] == WRITE_HEADER
    assert stream[3 : 3 + WRITE_LEAD_IN_BYTES] == bytes([GAP_BYTE]) * WRITE_LEAD_IN_BYTES
    assert stream[3 + WRITE_LEAD_IN_BYTES] != GAP_BYTE


def test_blocks_are_separated_by_the_factory_gap() -> None:
    payloads = [bytes([0x02, 0x00]), bytes([0x02, 0x01])]

    stream = encode_write_stream(payloads)

    first_end = 3 + WRITE_LEAD_IN_BYTES + 2 * len(framed(payloads[0]))
    assert stream[first_end : first_end + WRITE_GAP_BYTES] == bytes([GAP_BYTE]) * 250
    assert stream[first_end + WRITE_GAP_BYTES] != GAP_BYTE


def test_the_lead_in_is_the_factory_length() -> None:
    stream = encode_write_stream([bytes([0x02, 0x00])])

    assert stream[3 : 3 + 4501].count(GAP_BYTE) == 4500


def test_the_last_block_is_followed_by_a_gap_and_then_the_fill() -> None:
    payloads = [bytes([0x02, 0x00]), bytes([0x02, 0x01])]

    tail = tail_of(encode_write_stream(payloads), payloads)

    gap = len(tail) - len(tail.lstrip(bytes([GAP_BYTE])))
    assert WRITE_TAIL_GAP_BYTES <= gap < WRITE_TAIL_GAP_BYTES + len(FACTORY_FILL)
    assert tail[gap:] == FACTORY_FILL * ((len(tail) - gap) // 3)


def test_the_stream_fills_whole_packets_and_the_fill_ends_on_a_whole_pattern() -> None:
    payloads = [block.payload for block in calibration_disk(1).sides[0].blocks]

    stream = encode_write_stream(payloads)

    assert len(stream) % WRITE_PACKET_BYTES == 0
    assert len(stream) % len(FACTORY_FILL) == 0


def test_the_fill_plays_a_zero_and_two_ones_over_and_over_lowest_bits_first() -> None:
    values = unpack_in(WRITE_FILL, PackOrder.LOW_FIRST)

    assert values == bytes([ZERO_THEN_ONE, ONE, ONE]) * 4


def test_a_side_with_no_blocks_decodes_to_none() -> None:
    stream = encode_write_stream([])

    assert decode_write_stream(stream) == ()


def test_a_written_side_decodes_back_to_its_blocks() -> None:
    payloads = [block.payload for block in calibration_disk(1).sides[0].blocks]

    stream = encode_write_stream(payloads)

    assert decode_write_stream(stream) == tuple(payloads)


def test_the_values_of_a_side_stay_in_the_write_alphabet() -> None:
    payloads = [block.payload for block in calibration_disk(1).sides[0].blocks]

    values = unpack_raw03(encode_write_stream(payloads)[3:])

    assert set(values) <= {1, 2, 3}


def test_a_stream_without_the_header_is_refused() -> None:
    with pytest.raises(ValueError, match="does not start with the write header"):
        decode_write_stream(bytes(10))


def test_a_block_whose_checksum_does_not_match_is_refused() -> None:
    stream = bytearray(encode_write_stream([bytes([0x02, 0x00])]))
    stream[3 + WRITE_LEAD_IN_BYTES + 4] ^= 0xFF

    with pytest.raises(ValueError, match="checksum"):
        decode_write_stream(bytes(stream))


def test_a_block_of_a_kind_no_side_carries_is_refused() -> None:
    stream = bytearray(encode_write_stream([bytes([0x02, 0x00])]))
    stream[3 + WRITE_LEAD_IN_BYTES + 2] ^= 0xFF

    with pytest.raises(ValueError, match="which no side carries"):
        decode_write_stream(bytes(stream))
