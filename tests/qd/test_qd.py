from __future__ import annotations

import pytest

from fdstk.codecs.fds import decode as decode_fds
from fdstk.codecs.qd import SIDE_SIZE, CrcMode, decode, encode
from fdstk.core.blocks import CrcStatus
from fdstk.core.crc import block_crc, encode_crc
from fdstk.core.disk import Disk


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
