from __future__ import annotations

import pytest
from raw_kit import (
    LOST_PACKET_VALUES,
    UNAMBIGUOUS,
    calibration_values,
    encoded,
    file_pair,
    file_payloads,
    garbage_after,
    oversized,
    packed_low_first,
    sample_disk,
    two_blocks_with_gap,
    zero_runs_before_blocks,
)

from fdstoolkit.codecs.raw import (
    ADAPTER_BLIND_BITS,
    GAP_VALUE,
    MIN_GAP_VALUES,
    SHORTEST_GAP_BITS,
    SYNC_MARK,
    PackOrder,
    RawEncoding,
    block_regions,
    block_starts,
    decode_raw03,
    encode_block_stream,
    encode_era_b,
    encode_raw03,
    lead_in_bits,
    pack_order,
    pack_raw03,
    unpack_detected,
    unpack_raw03,
)
from fdstoolkit.core.bitstream import BITS_PER_BYTE, GAP_BITS, LEAD_IN_BITS
from fdstoolkit.core.crc import block_crc, encode_crc
from fdstoolkit.core.diagnostics import Severity


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


def test_a_gap_shorter_than_the_adapter_ignores_is_named_with_its_length() -> None:
    # Arrange
    values = two_blocks_with_gap(SHORTEST_GAP_BITS + 2)

    # Act
    _, findings = decode_raw03(values)

    # Assert
    short = [finding for finding in findings if finding.code == "FDS017"]
    assert len(short) == 1
    assert short[0].detail["bits"] in range(ADAPTER_BLIND_BITS)


def test_a_gap_the_adapter_reads_past_is_not_flagged() -> None:
    # Arrange
    values = two_blocks_with_gap(GAP_BITS)

    # Act
    _, findings = decode_raw03(values)

    # Assert
    assert "FDS017" not in [finding.code for finding in findings]


def test_undecodable_pulses_after_the_last_declared_block_are_information() -> None:
    # Arrange
    values = unpack_raw03(encode_raw03(sample_disk(files=1), side=0, encoding=RawEncoding.ERA_B))
    read = garbage_after(values)

    # Act
    _, findings = decode_raw03(read)

    # Assert
    trailing = [finding for finding in findings if finding.code == "FDS018"]
    assert [finding.severity for finding in trailing] == [Severity.INFO]
    assert "FDS015" not in [finding.code for finding in findings]


def test_a_lost_sync_mark_inside_the_declared_blocks_stays_a_warning() -> None:
    # Arrange
    first = bytes([0x80, 0x01]) + bytes(55)
    values = encoded(first + encode_crc(block_crc(first[1:]))) + encoded(
        bytes([0x41, 0x02, 0x00, 0x00])
    )

    # Act
    _, findings = decode_raw03(values)

    # Assert
    lost = [finding for finding in findings if finding.code == "FDS015"]
    assert [finding.detail["block"] for finding in lost] == [1]


def test_a_short_gap_names_the_block_it_precedes() -> None:
    # Arrange
    values = two_blocks_with_gap(SHORTEST_GAP_BITS + 2)

    # Act
    _, findings = decode_raw03(values)

    # Assert
    short = [finding for finding in findings if finding.code == "FDS017"]
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

    # Act
    _, findings = decode_raw03(values)

    # Assert
    named = [finding for finding in findings if finding.code == "FDS020"]
    assert [finding.severity for finding in named] == [Severity.INFO]
    assert "FDS015" not in [finding.code for finding in findings]


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
