from __future__ import annotations

import struct
from typing import Final

from fdstoolkit.flux.model import FluxCapture, FluxTrack, Revolution, Source

MAGIC: Final = b"SCP"
HEADER_SIZE: Final = 0x10
TABLE_OFFSET: Final = 0x10
MAX_TRACKS: Final = 168
TABLE_SIZE: Final = MAX_TRACKS * 4
TRACK_MAGIC: Final = b"TRK"
TRACK_HEADER_SIZE: Final = 4
REVOLUTION_ENTRY_SIZE: Final = 12
RESOLUTION_NS: Final = 25
OVERFLOW: Final = 0x10000
VERSION: Final = 0x22
FLAG_INDEX: Final = 0x01
FLAG_TPI: Final = 0x02
FLAG_RPM: Final = 0x04
FLAG_NORMALISED: Final = 0x08
FLAG_THIRD_PARTY: Final = 0x80
DISK_TYPE_OTHER: Final = 0x80
CHECKSUM_OFFSET: Final = 0x0C
CHECKSUM_MASK: Final = 0xFFFFFFFF


def is_scp(data: bytes) -> bool:
    return len(data) >= HEADER_SIZE and data.startswith(MAGIC)


def _tick_ns(resolution: int) -> int:
    return RESOLUTION_NS * (resolution + 1)


def _intervals(data: bytes, start: int, count: int, tick_ns: int) -> tuple[int, ...]:
    out: list[int] = []
    carry = 0
    for index in range(count):
        offset = start + index * 2
        if offset + 2 > len(data):
            break
        value = int.from_bytes(data[offset : offset + 2], "big")
        if value == 0:
            carry += OVERFLOW
            continue
        out.append((carry + value) * tick_ns)
        carry = 0
    return tuple(out)


def _read_track(data: bytes, offset: int, index: int, tick_ns: int, spins: int) -> FluxTrack:
    if offset + TRACK_HEADER_SIZE > len(data):
        message = f"track {index} points past the end of the capture"
        raise ValueError(message)
    if data[offset : offset + 3] != TRACK_MAGIC:
        message = f"track {index} does not start with the {TRACK_MAGIC.decode()} signature"
        raise ValueError(message)

    revolutions: list[Revolution] = []
    for spin in range(spins):
        entry = offset + TRACK_HEADER_SIZE + spin * REVOLUTION_ENTRY_SIZE
        if entry + REVOLUTION_ENTRY_SIZE > len(data):
            break
        _, length, relative = struct.unpack_from("<III", data, entry)
        revolutions.append(
            Revolution(intervals=_intervals(data, offset + relative, length, tick_ns))
        )

    if not revolutions:
        revolutions.append(Revolution(intervals=()))
    return FluxTrack(index=index, revolutions=tuple(revolutions))


def read_scp(data: bytes) -> FluxCapture:
    if not data.startswith(MAGIC):
        message = "not a SuperCard Pro capture"
        raise ValueError(message)
    if len(data) < HEADER_SIZE + TABLE_SIZE:
        message = f"a SuperCard Pro capture is at least {HEADER_SIZE + TABLE_SIZE} bytes, too short"
        raise ValueError(message)

    tick_ns = _tick_ns(data[0x0B])
    spins = max(1, data[0x05])
    tracks: list[FluxTrack] = []
    for index in range(MAX_TRACKS):
        (offset,) = struct.unpack_from("<I", data, TABLE_OFFSET + index * 4)
        if offset:
            tracks.append(_read_track(data, offset, index, tick_ns, spins))

    if not tracks:
        message = "the capture names no track"
        raise ValueError(message)

    return FluxCapture(source=Source.SCP, tracks=tuple(tracks), sample_ns=float(tick_ns))


def _encode_intervals(intervals: tuple[int, ...], tick_ns: int) -> bytes:
    out = bytearray()
    for interval in intervals:
        ticks = max(1, round(interval / tick_ns))
        while ticks >= OVERFLOW:
            out += b"\x00\x00"
            ticks -= OVERFLOW
        out += ticks.to_bytes(2, "big")
    return bytes(out)


def write_scp(capture: FluxCapture) -> bytes:
    tick_ns = RESOLUTION_NS
    indices = [track.index for track in capture.tracks]
    revolutions = max(track.revolution_count for track in capture.tracks)

    header = bytearray(HEADER_SIZE)
    header[0:3] = MAGIC
    header[0x03] = VERSION
    header[0x04] = DISK_TYPE_OTHER
    header[0x05] = revolutions
    header[0x06] = min(indices)
    header[0x07] = max(indices)
    header[0x08] = FLAG_INDEX | FLAG_THIRD_PARTY
    header[0x0B] = 0

    table = bytearray(TABLE_SIZE)
    body = bytearray()
    base = HEADER_SIZE + TABLE_SIZE

    for track in capture.tracks:
        offset = base + len(body)
        struct.pack_into("<I", table, track.index * 4, offset)

        entries = bytearray()
        payload = bytearray()
        table_size = TRACK_HEADER_SIZE + track.revolution_count * REVOLUTION_ENTRY_SIZE
        for revolution in track.revolutions:
            encoded = _encode_intervals(revolution.intervals, tick_ns)
            entries += struct.pack(
                "<III",
                revolution.duration_ns // tick_ns,
                len(encoded) // 2,
                table_size + len(payload),
            )
            payload += encoded

        body += TRACK_MAGIC + bytes([track.index]) + entries + payload

    out = bytearray(header + table + body)
    struct.pack_into("<I", out, CHECKSUM_OFFSET, sum(out[HEADER_SIZE:]) & CHECKSUM_MASK)
    return bytes(out)
