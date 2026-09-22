from __future__ import annotations

from fdstk.core.blocks import CrcStatus
from fdstk.core.crc import block_crc, encode_crc
from fdstk.core.parse import parse_side

FDS_SIDE = 65500


def disk_info() -> bytes:
    payload = bytearray(56)
    payload[0] = 0x01
    payload[1:15] = b"*NINTENDO-HVC*"
    payload[0x10:0x13] = b"SMB"
    return bytes(payload)


def file_amount(count: int) -> bytes:
    return bytes([0x02, count])


def file_header(number: int, size: int) -> bytes:
    return (
        bytes([0x03, number, number])
        + b"FILE    "
        + (0x6000).to_bytes(2, "little")
        + size.to_bytes(2, "little")
        + bytes([0x00])
    )


def file_data(size: int, fill: int = 0xAA) -> bytes:
    return bytes([0x04]) + bytes([fill]) * size


def build_side(*, files: int = 1, declared: int | None = None, crc: bool = False) -> bytes:
    payloads = [disk_info(), file_amount(files if declared is None else declared)]
    for index in range(files):
        payloads.append(file_header(index, 4))
        payloads.append(file_data(4))
    out = bytearray()
    for payload in payloads:
        out += payload
        if crc:
            out += encode_crc(block_crc(payload))
    return bytes(out)


def pad(data: bytes, size: int) -> bytes:
    return data.ljust(size, b"\0")


def test_a_well_formed_side_parses_every_block() -> None:
    side, findings = parse_side(pad(build_side(files=2), FDS_SIDE), has_crc=False)

    assert [block.kind for block in side.blocks] == [1, 2, 3, 4, 3, 4]
    assert side.file_count == 2
    assert findings == ()


def test_a_side_with_crcs_records_each_verdict() -> None:
    side, findings = parse_side(build_side(files=1, crc=True), has_crc=True)

    assert all(block.crc_status is CrcStatus.VALID for block in side.blocks)
    assert findings == ()


def test_a_wrong_crc_is_reported_with_both_values() -> None:
    raw = bytearray(build_side(files=1, crc=True))
    raw[56] ^= 0xFF

    _, findings = parse_side(bytes(raw), has_crc=True)

    codes = [finding.code for finding in findings]
    assert "FDS002" in codes
    mismatch = next(finding for finding in findings if finding.code == "FDS002")
    assert mismatch.detail["stored"] != mismatch.detail["computed"]


def test_a_null_crc_is_reported_but_not_an_error() -> None:
    payloads = [disk_info(), file_amount(0)]
    raw = b"".join(payload + bytes(2) for payload in payloads)

    _, findings = parse_side(raw, has_crc=True)

    codes = [finding.code for finding in findings]
    assert codes.count("FDS003") == 2
    assert "FDS002" not in codes


def test_an_unformatted_side_is_kept_whole_and_reported() -> None:
    side, findings = parse_side(bytes(FDS_SIDE), has_crc=False)

    assert side.blocks == ()
    assert len(side.tail) == FDS_SIDE
    assert [finding.code for finding in findings] == ["FDS001"]


def test_a_truncated_file_data_block_is_reported() -> None:
    raw = disk_info() + file_amount(1) + file_header(0, 4) + bytes([0x04, 0x01])

    side, findings = parse_side(raw, has_crc=False)

    assert "FDS004" in [finding.code for finding in findings]
    assert side.file_count == 0


def test_a_truncated_disk_info_block_is_reported() -> None:
    side, findings = parse_side(disk_info()[:20], has_crc=False)

    assert side.blocks == ()
    assert "FDS004" in [finding.code for finding in findings]


def test_files_past_the_declared_count_are_reported_as_hidden() -> None:
    side, findings = parse_side(build_side(files=3, declared=1), has_crc=False)

    assert side.hidden_file_count == 2
    hidden = next(finding for finding in findings if finding.code == "FDS006")
    assert hidden.detail["declared"] == 1
    assert hidden.detail["found"] == 3


def test_fewer_files_than_declared_are_reported() -> None:
    side, findings = parse_side(build_side(files=1, declared=4), has_crc=False)

    assert side.file_count == 1
    assert "FDS009" in [finding.code for finding in findings]


def test_data_after_the_last_block_is_reported() -> None:
    raw = build_side(files=1) + bytes(10) + bytes([0xEE, 0xFF])

    side, findings = parse_side(raw, has_crc=False)

    assert side.has_data_after_last_block
    tail = next(finding for finding in findings if finding.code == "FDS007")
    assert tail.detail["bytes"] == 2


def test_an_altered_verification_string_is_reported() -> None:
    raw = bytearray(build_side(files=0))
    raw[1:15] = b"*NOT-NINTENDO*"

    _, findings = parse_side(bytes(raw), has_crc=False)

    assert "FDS008" in [finding.code for finding in findings]


def test_an_unexpected_block_code_stops_the_walk_without_losing_bytes() -> None:
    raw = disk_info() + file_amount(1) + bytes([0x09, 0x09, 0x09])

    side, findings = parse_side(raw, has_crc=False)

    assert len(side.blocks) == 2
    assert side.tail == bytes([0x09, 0x09, 0x09])
    assert "FDS005" in [finding.code for finding in findings]


def test_the_side_records_the_capacity_it_was_parsed_from() -> None:
    side, _ = parse_side(pad(build_side(), FDS_SIDE), has_crc=False)

    assert side.capacity == FDS_SIDE


def test_diagnostics_carry_the_side_index() -> None:
    _, findings = parse_side(bytes(FDS_SIDE), has_crc=False, side_index=3)

    assert findings[0].side == 3
