from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from fdstoolkit.codecs.raw import (
    GAP_VALUE,
    LOW_FIRST_SHIFTS,
    MIN_GAP_VALUES,
    SYNC_MARK,
    VALUES_PER_BYTE,
    PackOrder,
    block_regions,
    encode_bits,
    expected_length,
    unpack_in,
)
from fdstoolkit.core.bitstream import BITS_PER_BYTE
from fdstoolkit.core.blocks import BlockKind, FileHeader
from fdstoolkit.core.crc import CRC_SIZE, block_crc, decode_crc, encode_crc

WRITE_HEADER: Final = bytes([0xC0, 0x00, 0xAB])
WRITE_GAP_BYTE: Final = 0xAA
WRITE_PACKET_BYTES: Final = 255
WRITE_FILL: Final = bytes([0x75, 0x5D, 0xD7])
WRITE_BIT_ONE: Final = 1
WRITE_ZERO_AFTER_ZERO: Final = 2
WRITE_ZERO_AFTER_ONE: Final = 3
HEADER_VALUES: Final = len(WRITE_HEADER) * VALUES_PER_BYTE
PACKET_VALUES: Final = WRITE_PACKET_BYTES * VALUES_PER_BYTE
SYNC_ZEROS: Final = SYNC_MARK.bit_length() - 1

WRITE_LEAD_IN_BITS: Final = 18000
WRITE_LEAD_IN_BYTES: Final = WRITE_LEAD_IN_BITS // VALUES_PER_BYTE
WRITE_GAP_BITS: Final = 999
WRITE_TAIL_GAP_BITS: Final = 976
FILL_START_BITS: Final = (1, 1, 0, 1, 0, 0, 0, 0, 0)
FILL_BITS: Final = (1, 1, 0)
UNDECIDED_END: Final = 2

FACTORY_GAP_BITS: Final = range(982, 1056)
FACTORY_END_GAP_BITS: Final = range(975, 977)


def _bits_of(data: bytes) -> list[int]:
    return [(byte >> index) & 1 for byte in data for index in range(BITS_PER_BYTE)]


def _framed(payload: bytes) -> bytes:
    return bytes([SYNC_MARK]) + payload + encode_crc(block_crc(payload))


def played_values(bits: Sequence[int]) -> bytes:
    out = bytearray()
    previous = 0
    for bit in bits:
        if bit:
            out.append(WRITE_BIT_ONE)
        else:
            out.append(WRITE_ZERO_AFTER_ONE if previous else WRITE_ZERO_AFTER_ZERO)
        previous = bit
    return bytes(out)


def _packed(values: bytes) -> bytes:
    return bytes(
        sum(value << shift for value, shift in zip(values[start:], LOW_FIRST_SHIFTS, strict=False))
        for start in range(0, len(values), VALUES_PER_BYTE)
    )


def _tail_gap(body: Sequence[int]) -> int:
    if body[-1:] == [1]:
        return WRITE_TAIL_GAP_BITS + 2
    return WRITE_TAIL_GAP_BITS + (1 if body[-2:-1] == [1] else 0)


def _side_bits(payloads: Sequence[bytes]) -> list[int]:
    body: list[int] = []
    for index, payload in enumerate(payloads):
        if index:
            body += [0] * WRITE_GAP_BITS
        body += _bits_of(_framed(payload))
    body += [0] * _tail_gap(body) + list(FILL_START_BITS)
    lead_in = WRITE_LEAD_IN_BITS + -(HEADER_VALUES + WRITE_LEAD_IN_BITS + len(body)) % len(
        FILL_BITS
    )
    bits = [0] * lead_in + body
    cycles = -(HEADER_VALUES + len(bits)) % PACKET_VALUES // len(FILL_BITS)
    return bits + list(FILL_BITS) * cycles


def stream_of(bits: Sequence[int]) -> bytes:
    return WRITE_HEADER + _packed(played_values(bits))


def encode_write_stream(payloads: Sequence[bytes]) -> bytes:
    return stream_of(_side_bits(payloads))


def written_bits(stream: bytes) -> list[int]:
    if not stream.startswith(WRITE_HEADER):
        message = "the stream does not start with the write header"
        raise ValueError(message)
    values = unpack_in(stream[len(WRITE_HEADER) :], PackOrder.LOW_FIRST)
    return [1 if value == WRITE_BIT_ONE else 0 for value in values]


def _zeros_from(bits: Sequence[int], start: int) -> int:
    index = start
    while index < len(bits) and not bits[index]:
        index += 1
    return index - start


def _byte_at(bits: Sequence[int], start: int) -> int:
    return sum(bit << index for index, bit in enumerate(bits[start : start + BITS_PER_BYTE]))


def _block_size(kind: int, pending: int) -> int:
    length = expected_length(kind, pending)
    if length is None:
        message = f"a written block has kind {kind:#04x}, which no side carries"
        raise ValueError(message)
    return 1 + length + CRC_SIZE


def _block_at(bits: Sequence[int], start: int, pending: int) -> bytes:
    size = _block_size(_byte_at(bits, start + BITS_PER_BYTE), pending)
    framed = bytes(_byte_at(bits, start + BITS_PER_BYTE * index) for index in range(size))
    payload = framed[1 : size - CRC_SIZE]
    if decode_crc(framed[size - CRC_SIZE :]) != block_crc(payload):
        kind = payload[0]
        message = f"a written block of kind {kind:#04x} carries a checksum its data does not match"
        raise ValueError(message)
    return payload


def _first_block(bits: Sequence[int]) -> int | None:
    zeros = _zeros_from(bits, 0) - SYNC_ZEROS
    if not WRITE_LEAD_IN_BITS <= zeros < WRITE_LEAD_IN_BITS + len(FILL_BITS):
        return None
    return zeros


def _next_block(bits: Sequence[int], end: int) -> int | None:
    if _zeros_from(bits, end) != WRITE_GAP_BITS + SYNC_ZEROS:
        return None
    return end + WRITE_GAP_BITS


def decode_write_stream(stream: bytes) -> tuple[bytes, ...]:
    bits = written_bits(stream)
    cursor = _first_block(bits)
    payloads: list[bytes] = []
    pending = 0
    while cursor is not None:
        payload = _block_at(bits, cursor, pending)
        if payload[0] == BlockKind.FILE_HEADER:
            pending = FileHeader.parse(payload).size
        payloads.append(payload)
        cursor = _next_block(bits, cursor + BITS_PER_BYTE * (len(payload) + 1 + CRC_SIZE))
    return tuple(payloads)


def _gaps(regions: Sequence[tuple[int, int]]) -> list[int]:
    return [regions[index + 1][0] - regions[index][1] for index in range(len(regions) - 1)]


def _outside(what: str, measured: int, allowed: range) -> str:
    return f"{what} of {measured} bits, outside the factory {allowed.start} to {allowed.stop - 1}"


def factory_violations(stream: bytes) -> tuple[str, ...]:
    classes = encode_bits(written_bits(stream))
    regions = block_regions(classes)
    problems = [
        _outside("a gap between blocks", gap, FACTORY_GAP_BITS)
        for gap in _gaps(regions)
        if gap not in FACTORY_GAP_BITS
    ]
    end_gap, rest = _end_run(classes[regions[-1][1] :] if regions else classes)
    if end_gap not in FACTORY_END_GAP_BITS:
        problems.append(_outside("the gap after the last block", end_gap, FACTORY_END_GAP_BITS))
    fill = encode_bits([*FILL_START_BITS, *FILL_BITS * len(rest)])
    decided = len(rest) - UNDECIDED_END
    if rest[:decided] != fill[:decided]:
        problems.append("the end of the track is not the factory fill")
    return tuple(problems)


def _end_run(tail: bytes) -> tuple[int, bytes]:
    run = 0
    found: tuple[int, int] = (0, len(tail))
    for index, value in enumerate(tail):
        if value == GAP_VALUE:
            run += 1
            continue
        if run >= MIN_GAP_VALUES:
            found = (run, index)
        run = 0
    return found[0], tail[found[1] :]
