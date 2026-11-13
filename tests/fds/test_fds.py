from __future__ import annotations

import pytest

from fdstoolkit.codecs.fds import build_header, decode, encode, has_header
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.diagnostics import Severity
from fdstoolkit.core.disk import HEADER_SIZE, SIDE_SIZE, Disk, Side


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


def header_refusal(count: int) -> str:
    with pytest.raises(ValueError, match="1 or 2") as raised:
        build_header(count)
    return str(raised.value)


def test_a_headerless_image_is_detected() -> None:
    # Arrange
    data = side_bytes()

    # Act
    result = has_header(data)

    # Assert
    assert not result


def test_a_headered_image_is_detected() -> None:
    # Arrange
    data = header(1) + side_bytes()

    # Act
    result = has_header(data)

    # Assert
    assert result


def test_a_four_byte_magic_without_the_right_size_is_not_a_header() -> None:
    # Arrange
    data = b"FDS\x1a" + bytes(10)

    # Act
    result = has_header(data)

    # Assert
    assert not result


def test_decode_reads_one_side_per_block_of_data() -> None:
    # Arrange
    data = side_bytes() * 2

    # Act
    disk, findings = decode(data)

    # Assert
    assert disk.side_count == 2
    assert disk.header_side_count is None
    assert findings == ()


def test_decode_reads_the_side_count_from_the_header() -> None:
    # Arrange
    data = header(2) + side_bytes() * 2

    # Act
    disk, _ = decode(data)

    # Assert
    assert disk.header_side_count == 2
    assert disk.side_count == 2


def test_decode_reports_a_header_that_disagrees_with_the_data() -> None:
    # Arrange
    data = header(3) + side_bytes() * 2

    # Act
    disk, findings = decode(data)

    # Assert
    assert disk.header_side_count is None
    assert "FDS013" in [finding.code for finding in findings]


def test_decode_reports_a_size_that_is_not_a_whole_number_of_sides() -> None:
    # Arrange
    data = side_bytes() + bytes(100)

    # Act
    disk, findings = decode(data)

    # Assert
    assert disk.side_count == 2
    assert "FDS010" in [finding.code for finding in findings]


def test_decode_keeps_an_unformatted_side() -> None:
    # Arrange
    data = bytes(SIDE_SIZE)

    # Act
    disk, findings = decode(data)

    # Assert
    assert disk.side_count == 1
    assert [finding.code for finding in findings] == ["FDS001"]


def test_encode_pads_each_side_to_the_nominal_size() -> None:
    # Arrange
    disk, _ = decode(side_bytes())

    # Act
    data, findings = encode(disk, headered=False)

    # Assert
    assert len(data) == SIDE_SIZE
    assert findings == ()


def test_encode_writes_a_header_when_asked() -> None:
    # Arrange
    disk, _ = decode(side_bytes() * 2)

    # Act
    data, _ = encode(disk, headered=True)

    # Assert
    assert data[:4] == b"FDS\x1a"
    assert data[4] == 2
    assert len(data) == HEADER_SIZE + 2 * SIDE_SIZE


def test_encode_round_trips_a_headerless_image() -> None:
    # Arrange
    original = side_bytes(files=3) + side_bytes(files=1)
    disk, _ = decode(original)

    # Act
    data, _ = encode(disk, headered=False)

    # Assert
    assert data == original


def test_encode_round_trips_an_unformatted_side() -> None:
    # Arrange
    original = bytes(SIDE_SIZE)
    disk, _ = decode(original)

    # Act
    data, _ = encode(disk, headered=False)

    # Assert
    assert data == original


def test_encode_reports_a_side_that_exceeds_the_nominal_size_without_dropping_data() -> None:
    # Arrange
    oversized = Side(
        blocks=(Block(kind=BlockKind.FILE_DATA, payload=bytes([0x04]) + bytes(SIDE_SIZE)),),
        tail=b"",
        capacity=SIDE_SIZE,
    )

    # Act
    data, findings = encode(Disk(sides=(oversized,)), headered=False)

    # Assert
    assert len(data) == SIDE_SIZE + 1
    assert "FDS011" in [finding.code for finding in findings]


def test_encode_rejects_a_disk_with_no_sides() -> None:
    # Arrange
    disk = Disk(sides=())
    headered = False

    # Act
    with pytest.raises(ValueError, match="at least one side") as raised:
        encode(disk, headered=headered)

    # Assert
    assert raised.type is ValueError


def test_build_header_rejects_a_side_count_out_of_range() -> None:
    # Arrange
    counts = (0, 3)

    # Act
    refusals = [header_refusal(count) for count in counts]

    # Assert
    assert refusals == [
        "a side count must be 1 or 2, got 0",
        "a side count must be 1 or 2, got 3",
    ]


def test_decode_of_an_empty_image_yields_no_sides() -> None:
    # Arrange
    data = b""

    # Act
    disk, findings = decode(data)

    # Assert
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
    # Arrange
    disk = side_with_data(declared=1, actual=300)
    headered = False

    # Act
    _, findings = encode(disk, headered=headered)

    # Assert
    assert [finding.code for finding in findings] == ["FDS016"]
    assert findings[0].detail == {"declared": 1, "actual": 300, "file": 0}


def test_a_data_block_shorter_than_its_header_is_flagged_as_lost_in_fds() -> None:
    # Arrange
    disk = side_with_data(declared=300, actual=100)
    headered = False

    # Act
    _, findings = encode(disk, headered=headered)

    # Assert
    assert [finding.code for finding in findings] == ["FDS012"]


def test_a_data_block_that_matches_its_header_raises_nothing() -> None:
    # Arrange
    disk = side_with_data(declared=100, actual=100)
    headered = False

    # Act
    _, findings = encode(disk, headered=headered)

    # Assert
    assert findings == ()


def with_trailing(extra: bytes) -> bytes:
    body = side_bytes().rstrip(b"\0") + extra
    return body.ljust(SIDE_SIZE, b"\0")


def test_a_test_data_block_after_the_last_file_is_named_as_information() -> None:
    # Arrange
    image = with_trailing(bytes([0x05]) + bytes([0x6D, 0xB6, 0xDB]) * 40)

    # Act
    _, findings = decode(image)

    # Assert
    named = [finding for finding in findings if finding.code == "FDS020"]
    assert [(finding.severity, finding.detail["pattern"]) for finding in named] == [
        (Severity.INFO, True)
    ]
    assert {"FDS005", "FDS007"}.isdisjoint(finding.code for finding in findings)


def test_a_type_5_block_without_the_test_pattern_is_named_without_it() -> None:
    # Arrange
    image = with_trailing(bytes([0x05, 0x12, 0x34, 0x56, 0x78]))

    # Act
    _, findings = decode(image)

    # Assert
    named = [finding for finding in findings if finding.code == "FDS020"]
    assert [finding.detail["pattern"] for finding in named] == [False]


def test_other_data_after_the_last_block_is_still_a_warning() -> None:
    # Arrange
    data = with_trailing(bytes([0x07, 0x01, 0x02]))

    # Act
    _, findings = decode(data)

    # Assert
    assert "FDS007" in [finding.code for finding in findings]
    assert "FDS020" not in [finding.code for finding in findings]
