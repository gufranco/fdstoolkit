from __future__ import annotations

from typing import Final

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.calibration import calibration_disk
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.raw import PackOrder, unpack_in
from fdstoolkit.codecs.write_stream import (
    WRITE_FILL,
    WRITE_HEADER,
    WRITE_PACKET_BYTES,
    decode_write_stream,
    encode_write_stream,
    factory_violations,
    played_values,
    stream_of,
    written_bits,
)
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.crc import block_crc, encode_crc
from fdstoolkit.core.disk import Disk
from fdstoolkit.edit.files import FileSpec, insert_file

MARKER: Final = 0x80
FACTORY_LEAD_IN: Final = 18000
FACTORY_GAP: Final = 999
FACTORY_TAIL: Final = 976
FILL: Final = [1, 1, 0]
FILL_START: Final = [1, 1, 0, 1, 0, 0, 0, 0, 0]
TAIL_GAPS: Final = (976, 977, 978)
FILLS_PER_PACKET: Final = 340
FILE_SIZES: Final = (1, 2, 3, 7, 64, 255, 1000, 8191)
WRITE_ALPHABET: Final = {1, 2, 3}


def bits_of(data: bytes) -> list[int]:
    return [(byte >> index) & 1 for byte in data for index in range(8)]


def framed(payload: bytes) -> bytes:
    return bytes([MARKER]) + payload + encode_crc(block_crc(payload))


def blank_side() -> list[bytes]:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    return [block.payload for block in disk.sides[0].blocks]


def side_with_file(size: int) -> list[bytes]:
    disk: Disk = decode(blank_image(sides=1, headered=False, formatted=True))[0]
    spec = FileSpec(
        name="FILE",
        address=0x6000,
        kind=FileKind.PROGRAM,
        data=bytes((index * 7 + size) & 0xFF for index in range(size)),
    )
    return [block.payload for block in insert_file(disk, side=0, spec=spec).sides[0].blocks]


def every_kind_of_side() -> list[list[bytes]]:
    calibration = calibration_disk(2)
    return [
        blank_side(),
        *([block.payload for block in side.blocks] for side in calibration.sides),
        *(side_with_file(size) for size in FILE_SIZES),
    ]


def factory_tail(last_block: list[int]) -> int:
    if last_block[-1]:
        return FACTORY_TAIL + 2
    return FACTORY_TAIL + last_block[-2]


def hand_built(*, gap: int, tail: int | None, fill: list[int]) -> bytes:
    first, second = blank_side()
    bits = [0] * FACTORY_LEAD_IN + bits_of(framed(first)) + [0] * gap
    last = bits_of(framed(second))
    bits += last + [0] * (factory_tail(last) if tail is None else tail) + FILL_START
    cycles = next(
        (count for count in range(400, 404) if (12 + len(bits) + len(fill) * count) % 4 == 0),
        400,
    )
    bits += fill * cycles
    bits += [0] * (-(12 + len(bits)) % 4)
    return stream_of(bits)


def test_the_marker_opens_a_block_with_seven_zeros_and_a_one() -> None:
    # Arrange
    bits = bits_of(framed(bytes([0x02, 0x00])))

    # Act
    values = played_values(bits)

    # Assert
    assert values[:8] == bytes([2, 2, 2, 2, 2, 2, 2, 1])


def test_every_byte_becomes_eight_values_in_the_write_alphabet() -> None:
    # Arrange
    block = framed(bytes(range(1, 40)))

    # Act
    values = played_values(bits_of(block))

    # Assert
    assert len(values) == 8 * len(block)
    assert set(values) <= WRITE_ALPHABET


def test_a_zero_after_a_one_is_a_long_value() -> None:
    # Arrange
    bits = bits_of(bytes([0b0000_0001]))

    # Act
    values = played_values(bits)

    # Assert
    assert values[:2] == bytes([1, 3])


def test_a_byte_plays_its_lowest_bit_first() -> None:
    # Arrange
    bits = bits_of(bytes([0x0F]))

    # Act
    values = played_values(bits)

    # Assert
    assert values == bytes([1, 1, 1, 1, 3, 2, 2, 2])


def test_a_one_a_zero_after_a_one_and_a_zero_after_a_zero_each_have_a_value() -> None:
    # Arrange
    bits = [1, 0, 0, 1, 1, 0]

    # Act
    values = played_values(bits)

    # Assert
    assert values == bytes([1, 3, 2, 1, 1, 3])


def test_the_stick_plays_the_lowest_bits_of_a_byte_first() -> None:
    # Arrange
    stream = WRITE_HEADER + bytes([0b01_11_10_01])

    # Act
    bits = written_bits(stream)

    # Assert
    assert bits == [1, 0, 0, 1]


def test_a_side_opens_with_the_header_and_the_lead_in() -> None:
    # Arrange
    stream = encode_write_stream(blank_side())

    # Act
    bits = written_bits(stream)

    # Assert
    assert stream[:3] == WRITE_HEADER
    assert bits[:FACTORY_LEAD_IN] == [0] * FACTORY_LEAD_IN
    assert 1 in bits[FACTORY_LEAD_IN : FACTORY_LEAD_IN + 10]


def test_the_lead_in_puts_the_first_block_where_a_factory_side_has_it() -> None:
    # Arrange
    bits = written_bits(encode_write_stream(blank_side()))

    # Act
    first_one = bits.index(1)

    # Assert
    assert FACTORY_LEAD_IN + 7 <= first_one < FACTORY_LEAD_IN + 10


def test_blocks_are_separated_by_the_factory_gap() -> None:
    # Arrange
    first, second = blank_side()
    bits = written_bits(encode_write_stream([first, second]))
    end = bits.index(1) - 7 + len(bits_of(framed(first)))

    # Act
    gap = bits[end:].index(1) - 7

    # Assert
    assert gap == FACTORY_GAP
    assert bits[end + gap + 7] == 1


def test_the_last_block_is_followed_by_a_gap_the_factory_fill_start_and_the_fill() -> None:
    # Arrange
    payloads = blank_side()
    bits = written_bits(encode_write_stream(payloads))
    start = bits.index(1) - 7
    end = (
        start + len(bits_of(framed(payloads[0]))) + FACTORY_GAP + len(bits_of(framed(payloads[1])))
    )
    tail = bits[end:]

    # Act
    gap = tail.index(1)

    # Assert
    assert gap in TAIL_GAPS
    assert tail[gap : gap + len(FILL_START)] == FILL_START
    assert tail[gap + len(FILL_START) :] == FILL * ((len(tail) - gap - len(FILL_START)) // 3)


def test_every_side_the_writer_makes_stays_inside_the_factory_layout() -> None:
    # Arrange
    sides = every_kind_of_side()

    # Act
    violations = [factory_violations(encode_write_stream(side)) for side in sides]

    # Assert
    assert violations == [()] * len(sides)


def test_the_stream_fills_whole_packets_and_ends_on_the_fill() -> None:
    # Arrange
    stream = encode_write_stream(blank_side())

    # Act
    bits = written_bits(stream)

    # Assert
    assert len(stream) % WRITE_PACKET_BYTES == 0
    assert bits[-6:] == FILL * 2


def test_the_values_of_a_side_stay_in_the_write_alphabet() -> None:
    # Arrange
    stream = encode_write_stream(blank_side())

    # Act
    values = unpack_in(stream[3:], PackOrder.LOW_FIRST)

    # Assert
    assert set(values) <= WRITE_ALPHABET


def test_a_blank_packet_carries_on_the_fill() -> None:
    # Arrange
    stream = WRITE_HEADER + WRITE_FILL * (WRITE_PACKET_BYTES // 3)

    # Act
    bits = written_bits(stream)

    # Assert
    assert bits == FILL * FILLS_PER_PACKET


def test_a_written_side_decodes_back_to_its_blocks() -> None:
    # Arrange
    sides = every_kind_of_side()

    # Act
    decoded = [decode_write_stream(encode_write_stream(side)) for side in sides]

    # Assert
    assert decoded == [tuple(side) for side in sides]


def test_a_side_with_no_blocks_decodes_to_none() -> None:
    # Arrange
    payloads: list[bytes] = []

    # Act
    stream = encode_write_stream(payloads)

    # Assert
    assert decode_write_stream(stream) == ()


def test_a_stream_without_the_header_is_refused() -> None:
    # Arrange
    stream = bytes(10)

    # Act
    with pytest.raises(ValueError, match="does not start with the write header") as raised:
        decode_write_stream(stream)

    # Assert
    assert raised.type is ValueError


def test_a_block_whose_checksum_does_not_match_is_refused() -> None:
    # Arrange
    bits = written_bits(encode_write_stream(blank_side()))
    bits[bits.index(1) + 28] ^= 1

    # Act
    with pytest.raises(ValueError, match="checksum") as raised:
        decode_write_stream(stream_of(bits))

    # Assert
    assert raised.type is ValueError


def test_a_block_of_a_kind_no_side_carries_is_refused() -> None:
    # Arrange
    bits = written_bits(encode_write_stream(blank_side()))
    bits[bits.index(1) + 6] ^= 1

    # Act
    with pytest.raises(ValueError, match="which no side carries") as raised:
        decode_write_stream(stream_of(bits))

    # Assert
    assert raised.type is ValueError


def test_a_short_gap_between_blocks_breaks_the_factory_layout() -> None:
    # Arrange
    stream = hand_built(gap=600, tail=None, fill=FILL)

    # Act
    problems = factory_violations(stream)

    # Assert
    assert len(problems) == 1
    assert problems[0].startswith("a gap between blocks of 60")


def test_a_short_gap_after_the_last_block_breaks_the_factory_layout() -> None:
    # Arrange
    stream = hand_built(gap=FACTORY_GAP, tail=900, fill=FILL)

    # Act
    problems = factory_violations(stream)

    # Assert
    assert len(problems) == 1
    assert problems[0].startswith("the gap after the last block of 90")


def test_an_end_of_track_other_than_the_fill_breaks_the_factory_layout() -> None:
    # Arrange
    stream = hand_built(gap=FACTORY_GAP, tail=None, fill=[0, 1])

    # Act
    problems = factory_violations(stream)

    # Assert
    assert problems == ("the end of the track is not the factory fill",)
