from __future__ import annotations

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode as decode_fds
from fdstoolkit.codecs.raw import (
    GAP_VALUE,
    LEAD_IN_PACKED,
    MIN_GAP_VALUES,
    VALUES_PER_BYTE,
    RawEncoding,
    class_histogram,
    decode_raw03,
    encode_era_b,
    encode_raw03,
    pack_raw03,
    quantise,
    to_read_alphabet,
    to_write_alphabet,
    unpack_raw03,
)
from fdstoolkit.core.crc import encode_crc


def sample_disk(files: int = 1):  # noqa: ANN201
    raw = bytearray(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    raw[56:58] = bytes([0x02, files])
    position = 58
    for index in range(files):
        header = (
            bytes([0x03, index, index])
            + b"FILE    "
            + (0x6000).to_bytes(2, "little")
            + (4).to_bytes(2, "little")
            + bytes([0x00])
        )
        raw[position : position + 16] = header
        position += 16
        raw[position : position + 5] = bytes([0x04]) + bytes([0xAA]) * 4
        position += 5
    disk, _ = decode_fds(bytes(raw))
    return disk


def test_unpacking_reads_four_values_per_byte_msb_first() -> None:
    assert unpack_raw03(bytes([0x1B])) == bytes([0, 1, 2, 3])
    assert unpack_raw03(bytes([0x55])) == bytes([1, 1, 1, 1])
    assert unpack_raw03(bytes([0xAA])) == bytes([2, 2, 2, 2])


def test_packing_reverses_unpacking() -> None:
    values = bytes([0, 1, 2, 3, 3, 2, 1, 0])

    assert unpack_raw03(pack_raw03(values)) == values


def test_packing_rejects_a_value_out_of_range() -> None:
    with pytest.raises(ValueError, match="between 0 and 3"):
        pack_raw03(bytes([4]))


def test_packing_pads_a_partial_group_with_zeros() -> None:
    assert unpack_raw03(pack_raw03(bytes([1, 2]))) == bytes([1, 2, 0, 0])


def test_quantising_uses_the_documented_thresholds() -> None:
    counts = bytes([0x00, 0x47, 0x48, 0x6F, 0x70, 0x9F, 0xA0, 0xCF, 0xD0, 0xFF])

    assert quantise(counts) == bytes([3, 3, 0, 0, 1, 1, 2, 2, 3, 3])


def test_a_histogram_counts_each_class() -> None:
    histogram = class_histogram(bytes([0, 0, 0, 1, 2, 3]))

    assert histogram[0] == 3
    assert histogram[1] == 1
    assert histogram[3] == 1


def test_a_stream_opens_with_a_lead_in_of_gap_values() -> None:
    values = unpack_raw03(encode_raw03(sample_disk(), side=0))

    assert values[:MIN_GAP_VALUES] == bytes([GAP_VALUE]) * MIN_GAP_VALUES


def test_a_stream_carries_eight_values_per_data_byte() -> None:
    disk = sample_disk()
    side = disk.sides[0]
    values = unpack_raw03(encode_raw03(disk, side=0))
    content = sum(block.size + 2 for block in side.blocks)

    assert len(values) > content * 8


def test_era_a_uses_the_published_nibble_table() -> None:
    disk = sample_disk()

    values = unpack_raw03(encode_raw03(disk, side=0, encoding=RawEncoding.ERA_A))

    assert set(values) <= {GAP_VALUE, 1, 2}


def test_the_write_alphabet_shifts_every_class_up_by_one() -> None:
    values = bytes([0, 1, 2])

    assert to_write_alphabet(values) == bytes([1, 2, 3])
    assert to_read_alphabet(to_write_alphabet(values)) == values


def test_a_stream_round_trips_back_to_the_same_blocks() -> None:
    disk = sample_disk(files=2)

    values = encode_raw03(disk, side=0, encoding=RawEncoding.ERA_B)
    rebuilt, findings = decode_raw03(unpack_raw03(values))

    assert [block.payload for block in rebuilt.blocks] == [
        block.payload for block in disk.sides[0].blocks
    ]
    assert [finding.code for finding in findings] == []


def test_every_decoded_block_carries_a_verified_crc() -> None:
    disk = sample_disk()

    rebuilt, _ = decode_raw03(unpack_raw03(encode_raw03(disk, side=0, encoding=RawEncoding.ERA_B)))

    assert all(block.stored_crc == block.computed_crc for block in rebuilt.blocks)


def test_a_stream_without_a_gap_decodes_to_nothing() -> None:
    side, findings = decode_raw03(bytes([1, 2, 1, 2] * 100))

    assert side.blocks == ()
    assert "FDS014" in [finding.code for finding in findings]


def test_a_corrupted_stream_reports_the_block_it_lost() -> None:
    disk = sample_disk(files=2)
    values = bytearray(unpack_raw03(encode_raw03(disk, side=0, encoding=RawEncoding.ERA_B)))
    start = LEAD_IN_PACKED * VALUES_PER_BYTE + 200
    values[start : start + 64] = bytes([0] * 64)

    _, findings = decode_raw03(bytes(values))

    assert findings


def test_encoding_an_unknown_side_is_refused() -> None:
    with pytest.raises(ValueError, match="no side 3"):
        encode_raw03(sample_disk(), side=3)


def encoded(data: bytes) -> bytes:
    return bytes([GAP_VALUE]) * MIN_GAP_VALUES + encode_era_b(data)


def test_a_region_whose_block_kind_is_unknown_is_reported() -> None:
    _, findings = decode_raw03(encoded(bytes([0x80, 0x09, 0x00, 0x00])))

    assert "FDS015" in [finding.code for finding in findings]


def test_a_region_without_the_sync_mark_is_reported() -> None:
    _, findings = decode_raw03(encoded(bytes([0x41, 0x02, 0x00, 0x00])))

    assert "FDS015" in [finding.code for finding in findings]


def test_a_region_cut_short_of_its_crc_is_reported() -> None:
    values = bytearray(encoded(bytes([0x80, 0x02, 0x01])))

    _, findings = decode_raw03(bytes(values))

    assert {"FDS004", "FDS015"} & {finding.code for finding in findings}


def test_a_block_whose_crc_does_not_match_is_reported() -> None:
    payload = bytes([0x02, 0x01])
    stream = encoded(bytes([0x80]) + payload + encode_crc(0x1234))

    _, findings = decode_raw03(stream)

    assert "FDS002" in [finding.code for finding in findings]
