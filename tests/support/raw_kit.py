from __future__ import annotations

import hashlib

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode as decode_fds
from fdstoolkit.codecs.raw import (
    GAP_VALUE,
    MARK_GAP_BITS,
    MIN_GAP_VALUES,
    RawEncoding,
    block_regions,
    encode_era_b,
    encode_raw03,
    unpack_raw03,
)
from fdstoolkit.core.crc import block_crc, encode_crc

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


def encoded(data: bytes) -> bytes:
    return bytes([GAP_VALUE]) * MIN_GAP_VALUES + encode_era_b(data)


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


def zero_runs_before_blocks(values: bytes) -> list[int]:
    runs: list[int] = []
    for start, _ in block_regions(values):
        run = 0
        while start - run - 1 >= 0 and values[start - run - 1] == GAP_VALUE:
            run += 1
        runs.append(run)
    return runs


def oversized(extra: int) -> bytes:
    return bytes((index * 7 + extra) & 0xFF for index in range(300 + extra))


UNAMBIGUOUS = [extra for extra in range(40) if block_crc(bytes([0x04]) + oversized(extra)) >> 8]


def two_blocks_with_gap(bits: int) -> bytes:
    first = bytes([0x80, 0x01]) + bytes(55)
    second = bytes([0x80, 0x02, 0x00])
    return (
        encoded(first + encode_crc(block_crc(first[1:])))
        + bytes([GAP_VALUE]) * (bits - MARK_GAP_BITS)
        + encode_era_b(second + encode_crc(block_crc(second[1:])))
    )


def garbage_after(values: bytes) -> bytes:
    return values + bytes([GAP_VALUE]) * MIN_GAP_VALUES + bytes([1, 2, 1, 2, 3, 2, 1]) * 40


def packed_low_first(values: bytes) -> bytes:
    padded = values + bytes(-len(values) % 4)
    return bytes(
        padded[index] | padded[index + 1] << 2 | padded[index + 2] << 4 | padded[index + 3] << 6
        for index in range(0, len(padded), 4)
    )


def calibration_values() -> bytes:
    return unpack_raw03(encode_raw03(sample_disk(files=2), side=0, encoding=RawEncoding.ERA_B))


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
