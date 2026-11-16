from __future__ import annotations

import zlib

from fdstoolkit.patch.formats import (
    write_varint,
)


def ips(records: list[tuple[int, bytes]], *, truncate: int | None = None) -> bytes:
    out = bytearray(b"PATCH")
    for offset, payload in records:
        out += offset.to_bytes(3, "big")
        out += len(payload).to_bytes(2, "big")
        out += payload
    out += b"EOF"
    if truncate is not None:
        out += truncate.to_bytes(3, "big")
    return bytes(out)


def ips_rle(offset: int, count: int, value: int) -> bytes:
    return (
        b"PATCH"
        + offset.to_bytes(3, "big")
        + (0).to_bytes(2, "big")
        + count.to_bytes(2, "big")
        + bytes([value])
        + b"EOF"
    )


def build_ups(source: bytes, target: bytes) -> bytes:
    out = bytearray(b"UPS1")
    out += write_varint(len(source))
    out += write_varint(len(target))
    position = 0
    previous = 0
    while position < len(target):
        original = source[position] if position < len(source) else 0
        if original == target[position]:
            position += 1
            continue
        start = position
        chunk = bytearray()
        while position < len(target):
            original = source[position] if position < len(source) else 0
            if original == target[position]:
                break
            chunk.append(original ^ target[position])
            position += 1
        out += write_varint(start - previous)
        out += bytes(chunk)
        out += b"\x00"
        previous = position + 1
    out += zlib.crc32(source).to_bytes(4, "little")
    out += zlib.crc32(target).to_bytes(4, "little")
    out += zlib.crc32(bytes(out)).to_bytes(4, "little")
    return bytes(out)


def build_bps(source: bytes, target: bytes) -> bytes:
    body = bytearray()
    body += write_varint(len(source))
    body += write_varint(len(target))
    body += write_varint(0)

    common = 0
    while common < min(len(source), len(target)) and source[common] == target[common]:
        common += 1

    if common:
        body += write_varint(((common - 1) << 2) | 0)
    remaining = target[common:]
    if remaining:
        body += write_varint(((len(remaining) - 1) << 2) | 1)
        body += remaining

    out = bytearray(b"BPS1")
    out += body
    out += zlib.crc32(source).to_bytes(4, "little")
    out += zlib.crc32(target).to_bytes(4, "little")
    out += zlib.crc32(bytes(out)).to_bytes(4, "little")
    return bytes(out)


HUGE = 2**32


def bps(source: bytes, target_size: int, actions: bytes) -> bytes:
    patch = bytearray(b"BPS1")
    patch += write_varint(len(source)) + write_varint(target_size) + write_varint(0) + actions
    patch += zlib.crc32(source).to_bytes(4, "little")
    patch += bytes(4)
    patch += zlib.crc32(bytes(patch)).to_bytes(4, "little")
    return bytes(patch)


def resealed(patch: bytes, *, target_crc: int) -> bytes:
    body = patch[: -2 * 4] + target_crc.to_bytes(4, "little")
    return body + zlib.crc32(body).to_bytes(4, "little")
