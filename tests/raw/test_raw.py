from __future__ import annotations

import hashlib

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode as decode_fds
from fdstoolkit.codecs.raw import (
    ADAPTER_BLIND_BITS,
    BITS_PER_BYTE,
    CLASS0_LIMIT,
    CLASS1_LIMIT,
    CLASS2_LIMIT,
    GAP_BITS,
    GAP_VALUE,
    LEAD_IN_BITS,
    MARK_GAP_BITS,
    MIN_GAP_VALUES,
    NOMINAL_LONG,
    NOMINAL_MEDIUM,
    NOMINAL_SHORT,
    SHORT_LIMIT,
    SHORTEST_GAP_BITS,
    SYNC_MARK,
    PackOrder,
    RawEncoding,
    block_regions,
    block_starts,
    class_histogram,
    decode_raw03,
    encode_block_stream,
    encode_era_b,
    encode_raw03,
    lead_in_bits,
    pack_order,
    pack_raw03,
    quantise,
    unpack_detected,
    unpack_raw03,
)
from fdstoolkit.core.crc import block_crc, encode_crc
from fdstoolkit.core.diagnostics import Severity

LOST_PACKET_VALUES = 254 * 4


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


CAPTURED = bytes(
    (
        0x3E,
        0x3E,
        0x3E,
        0x5D,
        0x3C,
        0x5F,
        0x3C,
        0x3F,
        0x3D,
        0x3E,
        0x3D,
        0x3E,
        0x5E,
        0x7C,
        0x7C,
        0x5C,
        0x3C,
        0x5D,
        0x3D,
        0x3E,
    )
)


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


def encoded(data: bytes) -> bytes:
    return bytes([GAP_VALUE]) * MIN_GAP_VALUES + encode_era_b(data)


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


def test_every_decoded_block_carries_where_it_starts_and_ends() -> None:
    # Arrange
    payloads = [bytes([0x01]) + bytes(55), bytes([0x02, 0x00])]
    values = unpack_raw03(encode_block_stream(payloads))

    # Act
    regions = block_regions(values)

    # Assert
    assert len(regions) == len(payloads)
    assert all(start < end for start, end in regions)
    assert regions[0][1] <= regions[1][0]
    assert block_starts(values) == tuple(start for start, _ in regions)


def file_payloads(*, declared: int, actual: bytes) -> list[bytes]:
    header = (
        bytes([0x03, 0, 0])
        + b"HIDDEN  "
        + (0x6000).to_bytes(2, "little")
        + declared.to_bytes(2, "little")
        + bytes([0x00])
    )
    info = sample_disk(0).sides[0].blocks[0].payload
    return [info, bytes([0x02, 1]), header, bytes([0x04]) + actual]


def test_a_data_block_longer_than_its_header_declares_is_read_whole() -> None:
    # Arrange
    actual = bytes(range(256)) * 3
    payloads = file_payloads(declared=1, actual=actual)

    # Act
    side, findings = decode_raw03(unpack_raw03(encode_block_stream(payloads)))

    # Assert
    assert [block.payload for block in side.blocks] == payloads
    assert side.blocks[3].crc_status.value == "valid"
    assert "FDS016" in [finding.code for finding in findings]


def test_a_data_block_whose_header_was_lost_is_still_read_whole() -> None:
    # Arrange
    actual = bytes(range(1, 200))
    payloads = file_payloads(declared=len(actual), actual=actual)
    del payloads[2]

    # Act
    side, _ = decode_raw03(unpack_raw03(encode_block_stream(payloads)))

    # Assert
    assert side.blocks[-1].payload == payloads[-1]
    assert side.blocks[-1].crc_status.value == "valid"


def test_a_damaged_data_block_keeps_its_declared_length() -> None:
    # Arrange
    actual = bytes(range(1, 200))
    payloads = file_payloads(declared=len(actual), actual=actual)
    damaged = payloads[3][:-1] + bytes([payloads[3][-1] ^ 0xFF])
    framed = bytes([SYNC_MARK]) + damaged + encode_crc(block_crc(payloads[3]))
    values = (
        unpack_raw03(encode_block_stream(payloads[:3]))
        + bytes([GAP_VALUE]) * MIN_GAP_VALUES
        + encode_era_b(framed)
        + bytes([GAP_VALUE]) * MIN_GAP_VALUES
    )

    # Act
    side, findings = decode_raw03(values)

    # Assert
    assert len(side.blocks[3].payload) == len(payloads[3])
    assert "FDS016" not in [finding.code for finding in findings]


def test_blocks_behind_the_shortest_gap_the_format_allows_are_read() -> None:
    # Arrange
    payloads = [block.payload for block in sample_disk(2).sides[0].blocks]
    values = bytearray(bytes([GAP_VALUE]) * (LEAD_IN_BITS))
    for index, payload in enumerate(payloads):
        if index:
            values += bytes([GAP_VALUE]) * SHORTEST_GAP_BITS
        values += encode_era_b(bytes([SYNC_MARK]) + payload + encode_crc(block_crc(payload)))

    # Act
    side, _ = decode_raw03(bytes(values))

    # Assert
    assert [block.payload for block in side.blocks] == payloads


def zero_runs_before_blocks(values: bytes) -> list[int]:
    runs: list[int] = []
    for start, _ in block_regions(values):
        run = 0
        while start - run - 1 >= 0 and values[start - run - 1] == GAP_VALUE:
            run += 1
        runs.append(run)
    return runs


def test_a_written_side_uses_the_lead_in_and_gaps_nintendo_wrote() -> None:
    # Arrange
    values = unpack_raw03(encode_raw03(sample_disk(2), side=0))

    # Act
    runs = zero_runs_before_blocks(values)

    # Assert
    assert runs[0] == LEAD_IN_BITS
    assert all(GAP_BITS <= run < GAP_BITS + BITS_PER_BYTE for run in runs[1:])
    assert LEAD_IN_BITS >= 26150
    assert GAP_BITS >= SHORTEST_GAP_BITS


def oversized(extra: int) -> bytes:
    return bytes((index * 7 + extra) & 0xFF for index in range(300 + extra))


UNAMBIGUOUS = [extra for extra in range(40) if block_crc(bytes([0x04]) + oversized(extra)) >> 8]


@pytest.mark.parametrize("extra", UNAMBIGUOUS)
def test_an_oversized_data_block_is_read_whole_when_another_file_follows(extra: int) -> None:
    # Arrange
    actual = oversized(extra)
    following = [
        bytes([0x03, 1, 1])
        + b"NEXT    "
        + (0x6000).to_bytes(2, "little")
        + (4).to_bytes(2, "little")
        + bytes([0]),
        bytes([0x04, 9, 9, 9, 9]),
    ]
    payloads = [*file_payloads(declared=1, actual=actual), *following]

    # Act
    side, _ = decode_raw03(unpack_raw03(encode_block_stream(payloads)))

    # Assert
    assert [block.payload for block in side.blocks] == payloads


def test_a_checksum_ending_in_zero_before_a_zero_gap_reads_one_byte_short() -> None:
    # Arrange
    extra = next(extra for extra in range(40) if extra not in UNAMBIGUOUS)
    payloads = file_payloads(declared=1, actual=oversized(extra))

    # Act
    side, _ = decode_raw03(unpack_raw03(encode_block_stream(payloads)))

    # Assert
    assert side.blocks[3].payload == payloads[3][:-1]
    assert side.blocks[3].crc_status.value == "valid"


def two_blocks_with_gap(bits: int) -> bytes:
    first = bytes([0x80, 0x01]) + bytes(55)
    second = bytes([0x80, 0x02, 0x00])
    return (
        encoded(first + encode_crc(block_crc(first[1:])))
        + bytes([GAP_VALUE]) * (bits - MARK_GAP_BITS)
        + encode_era_b(second + encode_crc(block_crc(second[1:])))
    )


def test_a_gap_shorter_than_the_adapter_ignores_is_named_with_its_length() -> None:
    # Arrange
    _, findings = decode_raw03(two_blocks_with_gap(SHORTEST_GAP_BITS + 2))

    # Act
    short = [finding for finding in findings if finding.code == "FDS017"]

    # Assert
    assert len(short) == 1
    assert short[0].detail["bits"] in range(ADAPTER_BLIND_BITS)


def test_a_gap_the_adapter_reads_past_is_not_flagged() -> None:
    # Arrange
    values = two_blocks_with_gap(GAP_BITS)

    # Act
    _, findings = decode_raw03(values)

    # Assert
    assert "FDS017" not in [finding.code for finding in findings]


def garbage_after(values: bytes) -> bytes:
    return values + bytes([GAP_VALUE]) * MIN_GAP_VALUES + bytes([1, 2, 1, 2, 3, 2, 1]) * 40


def test_undecodable_pulses_after_the_last_declared_block_are_information() -> None:
    # Arrange
    values = unpack_raw03(encode_raw03(sample_disk(files=1), side=0, encoding=RawEncoding.ERA_B))
    _, findings = decode_raw03(garbage_after(values))

    # Act
    trailing = [finding for finding in findings if finding.code == "FDS018"]

    # Assert
    assert [finding.severity for finding in trailing] == [Severity.INFO]
    assert "FDS015" not in [finding.code for finding in findings]


def test_a_lost_sync_mark_inside_the_declared_blocks_stays_a_warning() -> None:
    # Arrange
    first = bytes([0x80, 0x01]) + bytes(55)
    _, findings = decode_raw03(
        encoded(first + encode_crc(block_crc(first[1:]))) + encoded(bytes([0x41, 0x02, 0x00, 0x00]))
    )

    # Act
    lost = [finding for finding in findings if finding.code == "FDS015"]

    # Assert
    assert [finding.detail["block"] for finding in lost] == [1]


def test_a_short_gap_names_the_block_it_precedes() -> None:
    # Arrange
    _, findings = decode_raw03(two_blocks_with_gap(SHORTEST_GAP_BITS + 2))

    # Act
    short = [finding for finding in findings if finding.code == "FDS017"]

    # Assert
    assert short[0].detail["block"] == 1


def test_a_stream_without_a_sync_mark_has_no_lead_in() -> None:
    # Arrange
    values = bytes([1, 2, 1, 2] * 100)

    # Act
    result = lead_in_bits(values)

    # Assert
    assert result is None


def test_the_lead_in_counts_the_gap_right_before_the_first_block() -> None:
    # Arrange
    block = unpack_raw03(
        encode_block_stream([block.payload for block in sample_disk().sides[0].blocks])
    )
    stream = bytes([2, 1]) + block[LEAD_IN_BITS - MIN_GAP_VALUES :]

    # Act
    lead_in = lead_in_bits(stream)

    # Assert
    assert lead_in == MIN_GAP_VALUES


def test_a_sync_pulse_in_the_noise_before_the_lead_in_does_not_cut_it_short() -> None:
    # Arrange
    block = unpack_raw03(
        encode_block_stream([block.payload for block in sample_disk().sides[0].blocks])
    )
    noise = bytes([1, 2]) + bytes([GAP_VALUE]) * MIN_GAP_VALUES + bytes([1, 1, 1, 1])

    # Act
    lead_in = lead_in_bits(noise + block)

    # Assert
    assert lead_in == LEAD_IN_BITS


def test_noise_before_the_disk_information_block_is_not_part_of_the_side() -> None:
    # Arrange
    side = sample_disk().sides[0]
    block = unpack_raw03(encode_block_stream([block.payload for block in side.blocks]))
    noise = bytes([1, 2]) + bytes([GAP_VALUE]) * MIN_GAP_VALUES + bytes([1, 1, 1, 1])

    # Act
    decoded, findings = decode_raw03(noise + block)

    # Assert
    assert [found.payload for found in decoded.blocks] == [found.payload for found in side.blocks]
    assert findings == ()


def packed_low_first(values: bytes) -> bytes:
    padded = values + bytes(-len(values) % 4)
    return bytes(
        padded[index] | padded[index + 1] << 2 | padded[index + 2] << 4 | padded[index + 3] << 6
        for index in range(0, len(padded), 4)
    )


def calibration_values() -> bytes:
    return unpack_raw03(encode_raw03(sample_disk(files=2), side=0, encoding=RawEncoding.ERA_B))


def test_a_capture_packed_low_bits_first_is_recognised() -> None:
    # Arrange
    packed = packed_low_first(calibration_values())

    # Act
    order = pack_order(packed)

    # Assert
    assert order is PackOrder.LOW_FIRST


def test_a_capture_packed_low_bits_first_decodes_whole() -> None:
    # Arrange
    values = calibration_values()

    # Act
    side, _ = decode_raw03(unpack_detected(packed_low_first(values)))

    # Assert
    assert [block.payload for block in side.blocks] == [
        block.payload for block in decode_raw03(values)[0].blocks
    ]


def test_a_capture_in_the_device_order_keeps_it() -> None:
    # Arrange
    values = calibration_values()

    # Act
    packed = pack_raw03(values)

    # Assert
    assert pack_order(packed) is PackOrder.HIGH_FIRST
    assert unpack_detected(packed) == unpack_raw03(packed)


def test_a_capture_neither_order_decodes_keeps_the_device_order() -> None:
    # Arrange
    packed = bytes([0x1B]) * 4096

    # Act
    result = pack_order(packed)

    # Assert
    assert result is PackOrder.HIGH_FIRST


def test_a_test_data_block_in_a_capture_is_named_as_information() -> None:
    # Arrange
    values = calibration_values() + bytes([GAP_VALUE]) * GAP_BITS
    values += encode_era_b(bytes([SYNC_MARK, 0x05]) + bytes([0x6D, 0xB6, 0xDB]) * 20)
    _, findings = decode_raw03(values)

    # Act
    named = [finding for finding in findings if finding.code == "FDS020"]

    # Assert
    assert [finding.severity for finding in named] == [Severity.INFO]
    assert "FDS015" not in [finding.code for finding in findings]


def file_pair(number: int, size: int) -> list[bytes]:
    data = hashlib.shake_256(f"file{number}".encode()).digest(size)
    header = (
        bytes([0x03, number, number])
        + b"FILE    "
        + (0x6000).to_bytes(2, "little")
        + size.to_bytes(2, "little")
        + bytes([0x00])
    )
    return [header, bytes([0x04]) + data]


def test_a_block_cut_short_by_a_lost_packet_does_not_hide_the_blocks_after_it() -> None:
    # Arrange
    payloads = file_pair(0, 600) + file_pair(1, 300)
    values = unpack_raw03(encode_block_stream(payloads))
    start, end = block_regions(values)[1]
    middle = (start + end) // 2
    cut = values[:middle] + values[middle + LOST_PACKET_VALUES :]

    # Act
    side, _ = decode_raw03(cut)

    # Assert
    assert [block.payload for block in side.blocks][2:] == payloads[2:]
    assert side.blocks[1].stored_crc != side.blocks[1].computed_crc
