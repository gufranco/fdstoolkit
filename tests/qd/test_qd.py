from __future__ import annotations

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode as decode_fds
from fdstoolkit.codecs.qd import SIDE_SIZE, CrcMode, decode, encode
from fdstoolkit.core.blocks import CrcStatus
from fdstoolkit.core.crc import block_crc, encode_crc
from fdstoolkit.core.diagnostics import Severity
from fdstoolkit.core.disk import Disk


def disk_info() -> bytes:
    payload = bytearray(56)
    payload[0] = 0x01
    payload[1:15] = b"*NINTENDO-HVC*"
    payload[0x10:0x13] = b"SMB"
    return bytes(payload)


def blocks(files: int = 1) -> list[bytes]:
    out = [disk_info(), bytes([0x02, files])]
    for index in range(files):
        out.append(
            bytes([0x03, index, index])
            + b"FILE    "
            + (0x6000).to_bytes(2, "little")
            + (4).to_bytes(2, "little")
            + bytes([0x00])
        )
        out.append(bytes([0x04]) + bytes([0xAA]) * 4)
    return out


def side_bytes(files: int = 1, *, crc: bytes | None = None) -> bytes:
    out = bytearray()
    for payload in blocks(files):
        out += payload
        out += encode_crc(block_crc(payload)) if crc is None else crc
    return bytes(out).ljust(SIDE_SIZE, b"\0")


def test_decode_reads_one_side_per_block_of_data() -> None:
    disk, findings = decode(side_bytes() * 2)

    assert disk.side_count == 2
    assert findings == ()


def test_decode_keeps_the_stored_crc_of_every_block() -> None:
    disk, _ = decode(side_bytes())

    assert all(block.crc_status is CrcStatus.VALID for block in disk.sides[0].blocks)


def test_decode_reports_a_size_that_is_not_a_whole_number_of_sides() -> None:
    disk, findings = decode(side_bytes()[: SIDE_SIZE - 4096])

    assert disk.side_count == 1
    assert "FDS010" in [finding.code for finding in findings]


def test_encode_preserves_a_null_crc_by_default() -> None:
    original = side_bytes(crc=bytes(2))
    disk, _ = decode(original)

    data, _ = encode(disk)

    assert data == original


def test_encode_preserves_a_wrong_crc_by_default() -> None:
    original = side_bytes(crc=bytes([0x34, 0x12]))
    disk, _ = decode(original)

    data, _ = encode(disk)

    assert data == original


def test_encode_can_recompute_every_crc() -> None:
    disk, _ = decode(side_bytes(crc=bytes(2)))

    data, _ = encode(disk, crc_mode=CrcMode.COMPUTE)
    rebuilt, _ = decode(data)

    assert all(block.crc_status is CrcStatus.VALID for block in rebuilt.sides[0].blocks)


def test_encode_can_null_every_crc() -> None:
    disk, _ = decode(side_bytes())

    data, _ = encode(disk, crc_mode=CrcMode.NULL)
    rebuilt, _ = decode(data)

    assert all(block.crc_status is CrcStatus.NULL for block in rebuilt.sides[0].blocks)


def test_encode_computes_a_crc_that_is_missing_when_preserving() -> None:
    disk, _ = decode_fds(b"".join(blocks()).ljust(65500, b"\0"))

    data, _ = encode(disk)
    rebuilt, _ = decode(data)

    assert all(block.crc_status is CrcStatus.VALID for block in rebuilt.sides[0].blocks)


def test_encode_pads_each_side_to_the_nominal_size() -> None:
    disk, _ = decode(side_bytes())

    data, _ = encode(disk)

    assert len(data) == SIDE_SIZE


def test_encode_round_trips_an_unformatted_side() -> None:
    original = bytes(SIDE_SIZE)
    disk, _ = decode(original)

    data, _ = encode(disk)

    assert data == original


def test_encode_reports_a_side_that_exceeds_the_nominal_size() -> None:
    disk, _ = decode(side_bytes(files=1))
    oversized = Disk(
        sides=(
            disk.sides[0].__class__(
                blocks=disk.sides[0].blocks,
                tail=bytes(SIDE_SIZE),
                capacity=SIDE_SIZE,
            ),
        )
    )

    _, findings = encode(oversized)

    assert "FDS011" in [finding.code for finding in findings]


def test_encode_rejects_a_disk_with_no_sides() -> None:
    with pytest.raises(ValueError, match="at least one side"):
        encode(Disk(sides=()))


def test_a_side_longer_than_the_nominal_size_is_written_whole() -> None:
    disk, _ = decode(side_bytes())
    side = disk.sides[0]
    stuffed = Disk(
        sides=(side.__class__(blocks=side.blocks, tail=bytes(SIDE_SIZE), capacity=SIDE_SIZE),)
    )

    data, findings = encode(stuffed)

    assert len(data) > SIDE_SIZE
    assert "FDS011" in [finding.code for finding in findings]


def test_a_single_side_shorter_than_a_full_side_is_only_noted() -> None:
    disk, _ = decode_fds(blank_image(sides=1, headered=False, formatted=True))
    data, _ = encode(disk)

    _, findings = decode(data[:57344])

    finding = next(entry for entry in findings if entry.code == "FDS010")
    assert finding.severity is Severity.INFO
    assert finding.detail["short_single_side"] is True


def test_a_partial_second_side_is_still_a_warning() -> None:
    disk, _ = decode_fds(blank_image(sides=2, headered=False, formatted=True))
    data, _ = encode(disk)

    _, findings = decode(data[: 65536 + 100])

    finding = next(entry for entry in findings if entry.code == "FDS010")
    assert finding.severity is Severity.WARNING


DATA_OFFSET = 56 + 2 + 2 + 2 + 16 + 2


def with_long_data(payloads: list[bytes], *, actual: bytes) -> bytes:
    changed = [*payloads]
    changed[3] = bytes([0x04]) + actual
    out = bytearray()
    for payload in changed:
        out += payload + encode_crc(block_crc(payload))
    return bytes(out).ljust(SIDE_SIZE, b"\0")


def test_decode_reads_a_data_block_past_the_size_its_header_declares() -> None:
    actual = bytes(range(256)) * 2
    data = with_long_data(blocks(files=2), actual=actual)

    disk, findings = decode(data)

    assert disk.sides[0].blocks[3].payload == bytes([0x04]) + actual
    assert disk.sides[0].blocks[3].crc_status is CrcStatus.VALID
    assert len(disk.sides[0].blocks) == 6
    assert "FDS016" in [finding.code for finding in findings]


def test_decode_keeps_the_declared_size_of_a_damaged_data_block() -> None:
    payloads = blocks(files=1)
    data = bytearray(side_bytes(1))
    data[DATA_OFFSET + 2] ^= 0xFF

    disk, findings = decode(bytes(data))

    assert len(disk.sides[0].blocks[3].payload) == len(payloads[3])
    assert "FDS016" not in [finding.code for finding in findings]
