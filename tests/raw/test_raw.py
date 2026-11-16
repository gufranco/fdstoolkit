from __future__ import annotations

import pytest
from raw_kit import CAPTURED, encoded, sample_disk

from fdstoolkit.codecs.raw import (
    CLASS0_LIMIT,
    CLASS1_LIMIT,
    CLASS2_LIMIT,
    GAP_VALUE,
    MIN_GAP_VALUES,
    NOMINAL_LONG,
    NOMINAL_MEDIUM,
    NOMINAL_SHORT,
    SHORT_LIMIT,
    RawEncoding,
    class_histogram,
    decode_raw03,
    encode_raw03,
    pack_raw03,
    quantise,
    unpack_raw03,
)
from fdstoolkit.core.bitstream import LEAD_IN_BITS
from fdstoolkit.core.crc import encode_crc


def test_unpacking_reads_four_values_per_byte_msb_first() -> None:
    # Arrange
    packed = bytes([0x1B])

    # Act
    result = unpack_raw03(packed)

    # Assert
    assert result == bytes([0, 1, 2, 3])
    assert unpack_raw03(bytes([0x55])) == bytes([1, 1, 1, 1])
    assert unpack_raw03(bytes([0xAA])) == bytes([2, 2, 2, 2])


def test_packing_reverses_unpacking() -> None:
    # Arrange
    values = bytes([0, 1, 2, 3, 3, 2, 1, 0])

    # Act
    packed = pack_raw03(values)

    # Assert
    assert unpack_raw03(packed) == values


def test_packing_rejects_a_value_out_of_range() -> None:
    # Arrange
    values = bytes([4])

    # Act
    with pytest.raises(ValueError, match="between 0 and 3") as raised:
        pack_raw03(values)

    # Assert
    assert raised.type is ValueError


def test_packing_pads_a_partial_group_with_zeros() -> None:
    # Arrange
    packed = pack_raw03(bytes([1, 2]))

    # Act
    result = unpack_raw03(packed)

    # Assert
    assert result == bytes([1, 2, 0, 0])


def test_a_captured_pulse_train_quantises_onto_its_three_classes() -> None:
    # Arrange
    expected = bytes((0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 1, 2, 2, 1, 0, 1, 0, 0))

    # Act
    result = quantise(CAPTURED)

    # Assert
    assert result == expected


def test_the_nominal_counts_land_in_the_middle_of_their_classes() -> None:
    # Arrange
    counts = bytes((NOMINAL_SHORT, NOMINAL_MEDIUM, NOMINAL_LONG))

    # Act
    result = quantise(counts)

    # Assert
    assert result == bytes((0, 1, 2))


def test_a_pulse_too_short_or_too_long_to_be_data_is_rejected() -> None:
    # Arrange
    counts = bytes((0, SHORT_LIMIT - 1, CLASS2_LIMIT, 0xFF))

    # Act
    result = quantise(counts)

    # Assert
    assert result == bytes((3, 3, 3, 3))


def test_the_class_boundaries_sit_between_the_nominal_counts() -> None:
    # Arrange
    nominal = (NOMINAL_SHORT, NOMINAL_MEDIUM, NOMINAL_LONG)

    # Act
    limits = (CLASS0_LIMIT, CLASS1_LIMIT)

    # Assert
    assert nominal[0] < limits[0] < nominal[1]
    assert nominal[1] < limits[1] < nominal[2]


def test_a_histogram_counts_each_class() -> None:
    # Arrange
    values = bytes([0, 0, 0, 1, 2, 3])

    # Act
    histogram = class_histogram(values)

    # Assert
    assert histogram[0] == 3
    assert histogram[1] == 1
    assert histogram[3] == 1


def test_a_stream_opens_with_a_lead_in_of_gap_values() -> None:
    # Arrange
    packed = encode_raw03(sample_disk(), side=0)

    # Act
    values = unpack_raw03(packed)

    # Assert
    assert values[:MIN_GAP_VALUES] == bytes([GAP_VALUE]) * MIN_GAP_VALUES


def test_a_stream_carries_eight_values_per_data_byte() -> None:
    # Arrange
    disk = sample_disk()
    side = disk.sides[0]
    values = unpack_raw03(encode_raw03(disk, side=0))

    # Act
    content = sum(block.size + 2 for block in side.blocks)

    # Assert
    assert len(values) > content * 8


def test_era_a_uses_the_published_nibble_table() -> None:
    # Arrange
    disk = sample_disk()

    # Act
    values = unpack_raw03(encode_raw03(disk, side=0, encoding=RawEncoding.ERA_A))

    # Assert
    assert set(values) <= {GAP_VALUE, 1, 2}


def test_a_stream_round_trips_back_to_the_same_blocks() -> None:
    # Arrange
    disk = sample_disk(files=2)
    values = encode_raw03(disk, side=0, encoding=RawEncoding.ERA_B)

    # Act
    rebuilt, findings = decode_raw03(unpack_raw03(values))

    # Assert
    assert [block.payload for block in rebuilt.blocks] == [
        block.payload for block in disk.sides[0].blocks
    ]
    assert [finding.code for finding in findings] == []


def test_every_decoded_block_carries_a_verified_crc() -> None:
    # Arrange
    disk = sample_disk()

    # Act
    rebuilt, _ = decode_raw03(unpack_raw03(encode_raw03(disk, side=0, encoding=RawEncoding.ERA_B)))

    # Assert
    assert all(block.stored_crc == block.computed_crc for block in rebuilt.blocks)


def test_a_stream_without_a_gap_decodes_to_nothing() -> None:
    # Arrange
    values = bytes([1, 2, 1, 2] * 100)

    # Act
    side, findings = decode_raw03(values)

    # Assert
    assert side.blocks == ()
    assert "FDS014" in [finding.code for finding in findings]


def test_a_corrupted_stream_reports_the_block_it_lost() -> None:
    # Arrange
    disk = sample_disk(files=2)
    values = bytearray(unpack_raw03(encode_raw03(disk, side=0, encoding=RawEncoding.ERA_B)))
    start = LEAD_IN_BITS + 200
    values[start : start + 64] = bytes([0] * 64)

    # Act
    _, findings = decode_raw03(bytes(values))

    # Assert
    assert findings


def test_encoding_an_unknown_side_is_refused() -> None:
    # Arrange
    disk = sample_disk()
    side = 3

    # Act
    with pytest.raises(ValueError, match="no side 3") as raised:
        encode_raw03(disk, side=side)

    # Assert
    assert raised.type is ValueError


def test_a_region_whose_block_kind_is_unknown_is_reported() -> None:
    # Arrange
    values = encoded(bytes([0x80, 0x09, 0x00, 0x00]))

    # Act
    _, findings = decode_raw03(values)

    # Assert
    assert "FDS015" in [finding.code for finding in findings]


def test_a_region_without_the_sync_mark_is_reported() -> None:
    # Arrange
    values = encoded(bytes([0x41, 0x02, 0x00, 0x00]))

    # Act
    _, findings = decode_raw03(values)

    # Assert
    assert "FDS015" in [finding.code for finding in findings]


def test_a_region_cut_short_of_its_crc_is_reported() -> None:
    # Arrange
    values = bytearray(encoded(bytes([0x80, 0x02, 0x01])))

    # Act
    _, findings = decode_raw03(bytes(values))

    # Assert
    assert {"FDS004", "FDS015"} & {finding.code for finding in findings}


def test_a_block_whose_crc_does_not_match_is_reported() -> None:
    # Arrange
    payload = bytes([0x02, 0x01])
    stream = encoded(bytes([0x80]) + payload + encode_crc(0x1234))

    # Act
    _, findings = decode_raw03(stream)

    # Assert
    assert "FDS002" in [finding.code for finding in findings]
