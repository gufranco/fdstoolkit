from __future__ import annotations

import struct
from collections.abc import Sequence
from typing import Final

from fdstoolkit.flux.model import NS_PER_SECOND, FluxCapture, FluxTrack, Revolution, Source

MAGIC: Final = b"HXCPICFE"
HEADER_SIZE: Final = 512
BLOCK_SIZE: Final = 512
HALF_BLOCK: Final = 256
LUT_ENTRY_SIZE: Final = 4
MAX_TRACKS: Final = 256
BITS_PER_BYTE: Final = 8
ENCODING_UNKNOWN: Final = 0xFF
INTERFACE_SHUGART: Final = 0x07
WRITE_ALLOWED: Final = 0xFF
SINGLE_STEP: Final = 0xFF
DEFAULT_LUT_BLOCK: Final = 1
NS_PER_KBIT: Final = NS_PER_SECOND // 1000
CELLS_PER_BIT: Final = 2


def cell_ns(bit_rate_kbps: int) -> int:
    if bit_rate_kbps <= 0:
        message = "an HxC bit rate must be positive"
        raise ValueError(message)
    return NS_PER_KBIT // (bit_rate_kbps * CELLS_PER_BIT)


def bitcells_to_intervals(cells: bytes, *, cell_period_ns: int) -> tuple[int, ...]:
    out: list[int] = []
    run = 0
    seen = False
    for byte in cells:
        for position in range(BITS_PER_BYTE):
            run += 1
            if not (byte >> position) & 1:
                continue
            if seen:
                out.append(run * cell_period_ns)
            seen = True
            run = 0
    return tuple(out)


def intervals_to_bitcells(intervals: Sequence[int], *, cell_period_ns: int) -> bytes:
    bits = [1]
    for interval in intervals:
        cells = max(1, round(interval / cell_period_ns))
        bits.extend([0] * (cells - 1))
        bits.append(1)
    out = bytearray((len(bits) + BITS_PER_BYTE - 1) // BITS_PER_BYTE)
    for position, bit in enumerate(bits):
        if bit:
            out[position // BITS_PER_BYTE] |= 1 << (position % BITS_PER_BYTE)
    return bytes(out)


def is_hfe(data: bytes) -> bool:
    return data.startswith(MAGIC)


def _deinterleave(data: bytes, length: int) -> bytes:
    out = bytearray()
    for start in range(0, length, BLOCK_SIZE):
        out += data[start : start + HALF_BLOCK]
    return bytes(out)


def _interleave(cells: bytes) -> bytes:
    out = bytearray()
    for start in range(0, len(cells), HALF_BLOCK):
        chunk = cells[start : start + HALF_BLOCK].ljust(HALF_BLOCK, b"\0")
        out += chunk + bytes(HALF_BLOCK)
    return bytes(out)


def read_hfe(data: bytes) -> FluxCapture:
    if not data.startswith(MAGIC):
        message = "not an HxC image"
        raise ValueError(message)
    if len(data) < HEADER_SIZE:
        message = f"an HxC image is at least {HEADER_SIZE} bytes, too short"
        raise ValueError(message)

    track_count = data[0x09]
    if not track_count:
        message = "the image names no track"
        raise ValueError(message)

    (bit_rate,) = struct.unpack_from("<H", data, 0x0C)
    period = cell_ns(bit_rate)
    (lut_block,) = struct.unpack_from("<H", data, 0x12)
    lut = lut_block * BLOCK_SIZE
    if lut + track_count * LUT_ENTRY_SIZE > len(data):
        message = "the track table runs past the end of the image"
        raise ValueError(message)

    tracks: list[FluxTrack] = []
    for index in range(min(track_count, MAX_TRACKS)):
        offset, length = struct.unpack_from("<HH", data, lut + index * LUT_ENTRY_SIZE)
        raw = data[offset * BLOCK_SIZE : offset * BLOCK_SIZE + length]
        cells = _deinterleave(raw, length)
        tracks.append(
            FluxTrack(
                index=index,
                revolutions=(
                    Revolution(intervals=bitcells_to_intervals(cells, cell_period_ns=period)),
                ),
            )
        )

    return FluxCapture(source=Source.HFE, tracks=tuple(tracks), sample_ns=float(period))


def write_hfe(capture: FluxCapture, *, bit_rate_kbps: int = 250) -> bytes:
    period = cell_ns(bit_rate_kbps)
    count = capture.track_count

    header = bytearray(b"\xff" * HEADER_SIZE)
    header[0 : len(MAGIC)] = MAGIC
    header[0x08] = 0
    header[0x09] = count
    header[0x0A] = 1
    header[0x0B] = ENCODING_UNKNOWN
    struct.pack_into("<H", header, 0x0C, bit_rate_kbps)
    struct.pack_into("<H", header, 0x0E, 0)
    header[0x10] = INTERFACE_SHUGART
    header[0x11] = 0
    struct.pack_into("<H", header, 0x12, DEFAULT_LUT_BLOCK)
    header[0x14] = WRITE_ALLOWED
    header[0x15] = SINGLE_STEP
    header[0x16] = ENCODING_UNKNOWN
    header[0x17] = ENCODING_UNKNOWN
    header[0x18] = ENCODING_UNKNOWN
    header[0x19] = ENCODING_UNKNOWN

    lut = bytearray(BLOCK_SIZE)
    body = bytearray()
    first_data_block = DEFAULT_LUT_BLOCK + 1

    for slot, track in enumerate(capture.tracks):
        cells = intervals_to_bitcells(track.intervals(), cell_period_ns=period)
        stored = _interleave(cells)
        block = first_data_block + len(body) // BLOCK_SIZE
        struct.pack_into("<HH", lut, slot * LUT_ENTRY_SIZE, block, len(stored))
        body += stored

    return bytes(header + lut + body)
