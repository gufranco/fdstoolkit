from __future__ import annotations

import pytest

from fdstoolkit.core.crc import block_crc, decode_crc, encode_crc, prefix_crcs


def test_crc_of_a_file_amount_block_matches_the_drive_algorithm() -> None:
    block = bytes([0x02, 0x01])

    value = block_crc(block)

    assert value == 0x2ED5


def test_crc_stays_within_sixteen_bits_for_a_full_side() -> None:
    block = bytes(range(256)) * 16

    value = block_crc(block)

    assert 0 <= value <= 0xFFFF


def test_changing_one_byte_changes_the_crc() -> None:
    original = bytes([0x03, 0x01, 0x00, 0x41, 0x42])
    altered = bytes([0x03, 0x01, 0x00, 0x41, 0x43])

    assert block_crc(original) != block_crc(altered)


def test_encode_is_little_endian() -> None:
    assert encode_crc(0x1234) == bytes([0x34, 0x12])


def test_decode_reverses_encode() -> None:
    assert decode_crc(encode_crc(0xBEEF)) == 0xBEEF


def test_decode_rejects_a_short_slice() -> None:
    with pytest.raises(ValueError, match="needs 2 bytes"):
        decode_crc(bytes([0x01]))


def test_prefix_crcs_match_the_crc_of_every_prefix() -> None:
    data = bytes(range(40))

    found = prefix_crcs(data)

    assert found == tuple(block_crc(data[:size]) for size in range(len(data) + 1))
