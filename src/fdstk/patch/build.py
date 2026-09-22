from __future__ import annotations

import zlib
from typing import Final

from fdstk.patch.formats import (
    CRC_SIZE,
    IPS_END,
    IPS_MAGIC,
    LENGTH_SIZE,
    OFFSET_SIZE,
    UPS_MAGIC,
    PatchError,
    write_varint,
)

IPS_MAX_OFFSET: Final = 0xFFFFFF
MAX_RECORD: Final = 0xFFFF
EOF_OFFSET: Final = 0x454F46
MIN_RUN: Final = 4


def _runs(source: bytes, target: bytes) -> list[tuple[int, bytes]]:
    records: list[tuple[int, bytes]] = []
    start: int | None = None
    for index in range(len(target)):
        original = source[index] if index < len(source) else None
        if original != target[index]:
            if start is None:
                start = index
            continue
        if start is not None:
            records.append((start, target[start:index]))
            start = None
    if start is not None:
        records.append((start, target[start:]))
    return records


def _split(offset: int, payload: bytes) -> list[tuple[int, bytes]]:
    pieces: list[tuple[int, bytes]] = []
    for start in range(0, len(payload), MAX_RECORD):
        chunk = payload[start : start + MAX_RECORD]
        position = offset + start
        if position == EOF_OFFSET:
            pieces.append((position - 1, bytes([0x00]) + chunk))
            continue
        pieces.append((position, chunk))
    return pieces


def _encode_record(offset: int, payload: bytes) -> bytes:
    head = offset.to_bytes(OFFSET_SIZE, "big")
    if len(payload) >= MIN_RUN and len(set(payload)) == 1:
        return (
            head
            + (0).to_bytes(LENGTH_SIZE, "big")
            + len(payload).to_bytes(LENGTH_SIZE, "big")
            + payload[:1]
        )
    return head + len(payload).to_bytes(LENGTH_SIZE, "big") + payload


def _compress(payload: bytes) -> list[bytes]:
    pieces: list[bytes] = []
    run_start = 0
    for index in range(1, len(payload) + 1):
        if index < len(payload) and payload[index] == payload[run_start]:
            continue
        pieces.append(payload[run_start:index])
        run_start = index
    return pieces


def build_ips(source: bytes, target: bytes) -> bytes:
    if max(len(source), len(target)) > IPS_MAX_OFFSET:
        message = "the image is too large for the IPS format"
        raise PatchError(message)

    out = bytearray(IPS_MAGIC)
    for offset, payload in _runs(source, target):
        cursor = offset
        for piece in _compress(payload):
            for position, chunk in _split(cursor, piece):
                out += _encode_record(position, chunk)
            cursor += len(piece)
    out += IPS_END

    if len(target) < len(source):
        out += len(target).to_bytes(OFFSET_SIZE, "big")
    return bytes(out)


def _ups_runs(source: bytes, target: bytes) -> list[tuple[int, bytes]]:
    runs: list[tuple[int, bytes]] = []
    size = max(len(source), len(target))
    index = 0
    while index < size:
        before = source[index] if index < len(source) else 0
        after = target[index] if index < len(target) else 0
        if before == after:
            index += 1
            continue
        start = index
        xored = bytearray()
        while index < size:
            before = source[index] if index < len(source) else 0
            after = target[index] if index < len(target) else 0
            if before == after:
                break
            xored.append(before ^ after)
            index += 1
        runs.append((start, bytes(xored)))
    return runs


def build_ups(source: bytes, target: bytes) -> bytes:
    body = bytearray(UPS_MAGIC)
    body += write_varint(len(source))
    body += write_varint(len(target))

    position = 0
    for start, xored in _ups_runs(source, target):
        body += write_varint(start - position)
        body += xored
        body.append(0)
        position = start + len(xored) + 1

    body += zlib.crc32(source).to_bytes(CRC_SIZE, "little")
    body += zlib.crc32(target).to_bytes(CRC_SIZE, "little")
    body += zlib.crc32(bytes(body)).to_bytes(CRC_SIZE, "little")
    return bytes(body)
