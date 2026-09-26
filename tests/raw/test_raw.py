from __future__ import annotations

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode as decode_fds
from fdstoolkit.codecs.raw import (
    CLASS0_LIMIT,
    CLASS1_LIMIT,
    CLASS2_LIMIT,
    GAP_VALUE,
    LEAD_IN_PACKED,
    MIN_GAP_VALUES,
    NOMINAL_LONG,
    NOMINAL_MEDIUM,
    NOMINAL_SHORT,
    SHORT_LIMIT,
    SHORTEST_GAP_BITS,
    SYNC_MARK,
    VALUES_PER_BYTE,
    RawEncoding,
    block_regions,
    block_starts,
    class_histogram,
    decode_raw03,
    encode_block_stream,
    encode_era_b,
    encode_raw03,
    pack_raw03,
    quantise,
    to_read_alphabet,
    to_write_alphabet,
    unpack_raw03,
)
from fdstoolkit.core.crc import block_crc, encode_crc


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
    assert quantise(CAPTURED) == bytes((0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 1, 2, 2, 1, 0, 1, 0, 0))


def test_the_nominal_counts_land_in_the_middle_of_their_classes() -> None:
    assert quantise(bytes((NOMINAL_SHORT, NOMINAL_MEDIUM, NOMINAL_LONG))) == bytes((0, 1, 2))


def test_a_pulse_too_short_or_too_long_to_be_data_is_rejected() -> None:
    assert quantise(bytes((0, SHORT_LIMIT - 1, CLASS2_LIMIT, 0xFF))) == bytes((3, 3, 3, 3))


def test_the_class_boundaries_sit_between_the_nominal_counts() -> None:
    assert NOMINAL_SHORT < CLASS0_LIMIT < NOMINAL_MEDIUM
    assert NOMINAL_MEDIUM < CLASS1_LIMIT < NOMINAL_LONG


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


def test_every_decoded_block_carries_where_it_starts_and_ends() -> None:
    payloads = [bytes([0x01]) + bytes(55), bytes([0x02, 0x00])]
    values = unpack_raw03(encode_block_stream(payloads))

    regions = block_regions(values)

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
    actual = bytes(range(256)) * 3
    payloads = file_payloads(declared=1, actual=actual)

    side, findings = decode_raw03(unpack_raw03(encode_block_stream(payloads)))

    assert [block.payload for block in side.blocks] == payloads
    assert side.blocks[3].crc_status.value == "valid"
    assert "FDS016" in [finding.code for finding in findings]


def test_a_data_block_whose_header_was_lost_is_still_read_whole() -> None:
    actual = bytes(range(1, 200))
    payloads = file_payloads(declared=len(actual), actual=actual)
    del payloads[2]

    side, _ = decode_raw03(unpack_raw03(encode_block_stream(payloads)))

    assert side.blocks[-1].payload == payloads[-1]
    assert side.blocks[-1].crc_status.value == "valid"


def test_a_damaged_data_block_keeps_its_declared_length() -> None:
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

    side, findings = decode_raw03(values)

    assert len(side.blocks[3].payload) == len(payloads[3])
    assert "FDS016" not in [finding.code for finding in findings]


def test_blocks_behind_the_shortest_gap_the_format_allows_are_read() -> None:
    payloads = [block.payload for block in sample_disk(2).sides[0].blocks]
    values = bytearray(bytes([GAP_VALUE]) * (LEAD_IN_PACKED * VALUES_PER_BYTE))
    for index, payload in enumerate(payloads):
        if index:
            values += bytes([GAP_VALUE]) * SHORTEST_GAP_BITS
        values += encode_era_b(bytes([SYNC_MARK]) + payload + encode_crc(block_crc(payload)))

    side, _ = decode_raw03(bytes(values))

    assert [block.payload for block in side.blocks] == payloads
