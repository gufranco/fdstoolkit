from __future__ import annotations

from typing import Final

from fdstk.core.crc import CRC_SIZE, encode_crc
from fdstk.core.disk import Side

LEAD_IN_BITS: Final = 28300
GAP_BITS: Final = 976
GAP_TERMINATOR: Final = 0x80
BITS_PER_BYTE: Final = 8
TERMINATOR_SIZE: Final = 1
EMULATION_BUFFER: Final = 66560


def gap_length(bits: int) -> int:
    if bits < 0:
        message = f"a gap cannot be negative, got {bits} bits"
        raise ValueError(message)
    return bits // BITS_PER_BYTE


def _crc_bytes(stored: int | None, computed: int) -> bytes:
    return encode_crc(computed if stored is None else stored)


def encode_side_bitstream(side: Side) -> bytes:
    out = bytearray(gap_length(LEAD_IN_BITS))
    out.append(GAP_TERMINATOR)
    for index, block in enumerate(side.blocks):
        if index:
            out += bytes(gap_length(GAP_BITS))
            out.append(GAP_TERMINATOR)
        out += block.payload
        out += _crc_bytes(block.stored_crc, block.computed_crc)
    return bytes(out)


def emulated_side_size(side: Side) -> int:
    total = gap_length(LEAD_IN_BITS) + TERMINATOR_SIZE
    for index, block in enumerate(side.blocks):
        if index:
            total += gap_length(GAP_BITS) + TERMINATOR_SIZE
        total += block.size + CRC_SIZE
    return total


def fits_emulation_buffer(side: Side) -> bool:
    return emulated_side_size(side) <= EMULATION_BUFFER
