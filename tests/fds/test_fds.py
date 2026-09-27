from __future__ import annotations

import pytest

from fdstoolkit.codecs.fds import HEADER_SIZE, SIDE_SIZE, build_header, decode, encode, has_header
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.diagnostics import Severity
from fdstoolkit.core.disk import Disk, Side


def disk_info() -> bytes:
    payload = bytearray(56)
    payload[0] = 0x01
    payload[1:15] = b"*NINTENDO-HVC*"
    payload[0x10:0x13] = b"SMB"
    return bytes(payload)


def side_bytes(files: int = 1) -> bytes:
    out = bytearray(disk_info())
    out += bytes([0x02, files])
    for index in range(files):
        out += (
            bytes([0x03, index, index])
            + b"FILE    "
            + (0x6000).to_bytes(2, "little")
            + (4).to_bytes(2, "little")
            + bytes([0x00])
        )
        out += bytes([0x04]) + bytes([0xAA]) * 4
    return bytes(out).ljust(SIDE_SIZE, b"\0")


def header(sides: int) -> bytes:
    return b"FDS\x1a" + bytes([sides]) + bytes(11)


def test_a_headerless_image_is_detected() -> None:
    assert not has_header(side_bytes())


def test_a_headered_image_is_detected() -> None:
    assert has_header(header(1) + side_bytes())


def test_a_four_byte_magic_without_the_right_size_is_not_a_header() -> None:
    assert not has_header(b"FDS\x1a" + bytes(10))


def test_decode_reads_one_side_per_block_of_data() -> None:
    disk, findings = decode(side_bytes() * 2)

    assert disk.side_count == 2
    assert disk.header_side_count is None
    assert findings == ()


def test_decode_reads_the_side_count_from_the_header() -> None:
    disk, _ = decode(header(2) + side_bytes() * 2)

    assert disk.header_side_count == 2
    assert disk.side_count == 2


def test_decode_reports_a_header_that_disagrees_with_the_data() -> None:
    disk, findings = decode(header(3) + side_bytes() * 2)

    assert disk.header_side_count is None
    assert "FDS013" in [finding.code for finding in findings]


def test_decode_reports_a_size_that_is_not_a_whole_number_of_sides() -> None:
    disk, findings = decode(side_bytes() + bytes(100))

    assert disk.side_count == 2
    assert "FDS010" in [finding.code for finding in findings]


def test_decode_keeps_an_unformatted_side() -> None:
    disk, findings = decode(bytes(SIDE_SIZE))

    assert disk.side_count == 1
    assert [finding.code for finding in findings] == ["FDS001"]


def test_encode_pads_each_side_to_the_nominal_size() -> None:
    disk, _ = decode(side_bytes())

    data, findings = encode(disk, headered=False)

    assert len(data) == SIDE_SIZE
    assert findings == ()


def test_encode_writes_a_header_when_asked() -> None:
    disk, _ = decode(side_bytes() * 2)

    data, _ = encode(disk, headered=True)

    assert data[:4] == b"FDS\x1a"
    assert data[4] == 2
    assert len(data) == HEADER_SIZE + 2 * SIDE_SIZE


def test_encode_round_trips_a_headerless_image() -> None:
    original = side_bytes(files=3) + side_bytes(files=1)
    disk, _ = decode(original)

    data, _ = encode(disk, headered=False)

    assert data == original


def test_encode_round_trips_an_unformatted_side() -> None:
    original = bytes(SIDE_SIZE)
    disk, _ = decode(original)

    data, _ = encode(disk, headered=False)

    assert data == original


def test_encode_reports_a_side_that_exceeds_the_nominal_size_without_dropping_data() -> None:
    oversized = Side(
        blocks=(Block(kind=BlockKind.FILE_DATA, payload=bytes([0x04]) + bytes(SIDE_SIZE)),),
        tail=b"",
        capacity=SIDE_SIZE,
    )

    data, findings = encode(Disk(sides=(oversized,)), headered=False)

    assert len(data) == SIDE_SIZE + 1
    assert "FDS011" in [finding.code for finding in findings]


def test_encode_rejects_a_disk_with_no_sides() -> None:
    with pytest.raises(ValueError, match="at least one side"):
        encode(Disk(sides=()), headered=False)


def test_build_header_rejects_a_side_count_out_of_range() -> None:
    with pytest.raises(ValueError, match="1 or 2, got 0"):
        build_header(0)
    with pytest.raises(ValueError, match="1 or 2, got 3"):
        build_header(3)


def test_decode_of_an_empty_image_yields_no_sides() -> None:
    disk, findings = decode(b"")

    assert disk.side_count == 0
    assert findings == ()


def side_with_data(declared: int, actual: int) -> Disk:
    info = Block(kind=BlockKind.DISK_INFO, payload=disk_info())
    amount = Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([0x02, 1]))
    header_block = Block(
        kind=BlockKind.FILE_HEADER,
        payload=bytes([0x03, 0, 0])
        + b"FILE    "
        + (0x6000).to_bytes(2, "little")
        + declared.to_bytes(2, "little")
        + bytes([0]),
    )
    data = Block(kind=BlockKind.FILE_DATA, payload=bytes([0x04]) + bytes(actual))
    return Disk(
        sides=(Side(blocks=(info, amount, header_block, data), tail=b"", capacity=SIDE_SIZE),)
    )


def test_a_data_block_longer_than_its_header_is_flagged_as_lost_in_fds() -> None:
    _, findings = encode(side_with_data(declared=1, actual=300), headered=False)

    assert [finding.code for finding in findings] == ["FDS016"]
    assert findings[0].detail == {"declared": 1, "actual": 300, "file": 0}


def test_a_data_block_shorter_than_its_header_is_flagged_as_lost_in_fds() -> None:
    _, findings = encode(side_with_data(declared=300, actual=100), headered=False)

    assert [finding.code for finding in findings] == ["FDS012"]


def test_a_data_block_that_matches_its_header_raises_nothing() -> None:
    _, findings = encode(side_with_data(declared=100, actual=100), headered=False)

    assert findings == ()


def with_trailing(extra: bytes) -> bytes:
    body = side_bytes().rstrip(b"\0") + extra
    return body.ljust(SIDE_SIZE, b"\0")


def test_a_test_data_block_after_the_last_file_is_named_as_information() -> None:
    _, findings = decode(with_trailing(bytes([0x05]) + bytes([0x6D, 0xB6, 0xDB]) * 40))

    named = [finding for finding in findings if finding.code == "FDS020"]
    assert [(finding.severity, finding.detail["pattern"]) for finding in named] == [
        (Severity.INFO, True)
    ]
    assert {"FDS005", "FDS007"}.isdisjoint(finding.code for finding in findings)


def test_a_type_5_block_without_the_test_pattern_is_named_without_it() -> None:
    _, findings = decode(with_trailing(bytes([0x05, 0x12, 0x34, 0x56, 0x78])))

    named = [finding for finding in findings if finding.code == "FDS020"]
    assert [finding.detail["pattern"] for finding in named] == [False]


def test_other_data_after_the_last_block_is_still_a_warning() -> None:
    _, findings = decode(with_trailing(bytes([0x07, 0x01, 0x02])))

    assert "FDS007" in [finding.code for finding in findings]
    assert "FDS020" not in [finding.code for finding in findings]
