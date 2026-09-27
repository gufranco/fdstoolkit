from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Final

from fdstoolkit.core.blocks import (
    DISK_INFO_SIZE,
    FILE_AMOUNT_SIZE,
    FILE_HEADER_SIZE,
    Block,
    BlockKind,
    FileHeader,
    declared_blocks,
)
from fdstoolkit.core.crc import CRC_SIZE, block_crc, crc_boundary, decode_crc, encode_crc
from fdstoolkit.core.diagnostics import CODES, Diagnostic, Severity
from fdstoolkit.core.disk import Disk, Side

VALUES_PER_BYTE: Final = 4
LOW_FIRST_SHIFTS: Final = (0, 2, 4, 6)
ORDER_PROBE_BYTES: Final = 16384
MAX_CLASS: Final = 3
GAP_VALUE: Final = 0
SYNC_VALUE: Final = 1
SHORTEST_GAP_BITS: Final = 480
MIN_GAP_VALUES: Final = SHORTEST_GAP_BITS
LEAD_IN_BITS: Final = 28300
GAP_BITS: Final = 976
ADAPTER_BLIND_BITS: Final = 488
GAP_FILL: Final = 0xAA
WRITE_HEADER: Final = bytes([0xC0, 0x00, 0xAB])
WRITE_GAP_BYTE: Final = 0xAA
WRITE_LEAD_IN_BYTES: Final = 6750
WRITE_GAP_BYTES: Final = 224
WRITE_PACKET_BYTES: Final = 255
WRITE_BIT_ONE: Final = 1
WRITE_ZERO_THEN_ZERO: Final = 2
WRITE_ZERO_THEN_ONE: Final = 3
NIBBLE_BITS: Final = 4
GAP_BYTES: Final = frozenset({0x00, 0xFF})
BYTE_VALUES: Final = 8
SYNC_MARK: Final = 0x80
CAPTURE_CLOCK_HZ: Final = 6_000_000
KEY_ONE_ONE: Final = 0x11
KEY_ZERO_ZERO: Final = 0x00
KEY_ONE_TWO: Final = 0x12
KEY_ZERO_ONE: Final = 0x01
KEY_ONE_ZERO: Final = 0x10
HEADER_BITS: Final = 16
BITS_PER_BYTE: Final = 8

NOMINAL_SHORT: Final = 62
NOMINAL_MEDIUM: Final = 93
NOMINAL_LONG: Final = 124
SHORT_LIMIT: Final = NOMINAL_SHORT * 7 // 10
CLASS0_LIMIT: Final = (NOMINAL_SHORT + NOMINAL_MEDIUM) // 2
CLASS1_LIMIT: Final = (NOMINAL_MEDIUM + NOMINAL_LONG) // 2
CLASS2_LIMIT: Final = NOMINAL_LONG * 3 // 2

ERA_A_NIBBLE: Final = (
    0xAA,
    0xA9,
    0xA6,
    0xA5,
    0x9A,
    0x99,
    0x96,
    0x95,
    0x6A,
    0x69,
    0x66,
    0x65,
    0x5A,
    0x59,
    0x56,
    0x55,
)


class RawEncoding(StrEnum):
    ERA_A = "era-a"
    ERA_B = "era-b"


def quantise(counts: bytes, scale: float = 1.0) -> bytes:
    limits = (SHORT_LIMIT * scale, CLASS0_LIMIT * scale, CLASS1_LIMIT * scale, CLASS2_LIMIT * scale)
    out = bytearray()
    for count in counts:
        if count < limits[0]:
            out.append(MAX_CLASS)
        elif count < limits[1]:
            out.append(0)
        elif count < limits[2]:
            out.append(1)
        elif count < limits[3]:
            out.append(2)
        else:
            out.append(MAX_CLASS)
    return bytes(out)


class PackOrder(StrEnum):
    HIGH_FIRST = "high bits first"
    LOW_FIRST = "low bits first"


def _unpack_low_first(packed: bytes) -> bytes:
    return bytes(byte >> shift & 0x03 for byte in packed for shift in LOW_FIRST_SHIFTS)


def unpack_in(packed: bytes, order: PackOrder) -> bytes:
    return unpack_raw03(packed) if order is PackOrder.HIGH_FIRST else _unpack_low_first(packed)


def pack_order(packed: bytes) -> PackOrder:
    probe = packed[:ORDER_PROBE_BYTES]
    for order in (PackOrder.HIGH_FIRST, PackOrder.LOW_FIRST):
        side, _ = decode_raw03(unpack_in(probe, order))
        if any(block.stored_crc == block.computed_crc for block in side.blocks):
            return order
    return PackOrder.HIGH_FIRST


def unpack_detected(packed: bytes) -> bytes:
    return unpack_in(packed, pack_order(packed))


def decode_packed(packed: bytes) -> tuple[Side, tuple[Diagnostic, ...]]:
    order = pack_order(packed)
    side, findings = decode_raw03(unpack_in(packed, order))
    if order is PackOrder.HIGH_FIRST:
        return side, findings
    return side, (*findings, _diagnostic("FDS019", Severity.INFO, {"order": order.value}))


def unpack_raw03(packed: bytes) -> bytes:
    out = bytearray()
    for byte in packed:
        out.append((byte >> 6) & 0x03)
        out.append((byte >> 4) & 0x03)
        out.append((byte >> 2) & 0x03)
        out.append(byte & 0x03)
    return bytes(out)


def pack_raw03(values: bytes) -> bytes:
    if any(value > MAX_CLASS for value in values):
        message = "a pulse class is between 0 and 3"
        raise ValueError(message)
    padded = bytes(values).ljust(
        ((len(values) + VALUES_PER_BYTE - 1) // VALUES_PER_BYTE) * VALUES_PER_BYTE,
        b"\0",
    )
    return bytes(
        (padded[index] << 6)
        | (padded[index + 1] << 4)
        | (padded[index + 2] << 2)
        | padded[index + 3]
        for index in range(0, len(padded), VALUES_PER_BYTE)
    )


def class_histogram(values: bytes) -> dict[int, int]:
    return {value: values.count(value) for value in range(MAX_CLASS + 1)}


def _bits_lsb_first(data: bytes) -> list[int]:
    return [(byte >> index) & 1 for byte in data for index in range(8)]


def _encode_bits(bits: list[int]) -> bytes:
    out = bytearray()
    previous = 1
    index = 0
    while index < len(bits):
        bit = bits[index]
        if previous == 1:
            if bit == 1:
                out.append(0)
                index += 1
                continue
            following = bits[index + 1] if index + 1 < len(bits) else 0
            out.append(1 if following == 0 else 2)
            previous = 0 if following == 0 else 1
            index += 2
            continue
        out.append(0 if bit == 0 else 1)
        previous = bit
        index += 1
    return bytes(out)


def encode_era_b(data: bytes) -> bytes:
    return _encode_bits(_bits_lsb_first(data))


def encode_era_a(data: bytes) -> bytes:
    out = bytearray()
    for byte in data:
        out += unpack_raw03(bytes([ERA_A_NIBBLE[byte & 0x0F]]))
        out += unpack_raw03(bytes([ERA_A_NIBBLE[(byte >> 4) & 0x0F]]))
    return bytes(out)


def encode_block_stream(
    payloads: Sequence[bytes],
    *,
    encoding: RawEncoding = RawEncoding.ERA_B,
) -> bytes:
    encoder = encode_era_a if encoding is RawEncoding.ERA_A else encode_era_b
    values = bytearray(bytes([GAP_VALUE]) * LEAD_IN_BITS)

    for index, payload in enumerate(payloads):
        if index:
            values += bytes([GAP_VALUE]) * GAP_BITS
        framed = bytes([SYNC_MARK]) + payload + encode_crc(block_crc(payload))
        values += encoder(framed)

    return pack_raw03(bytes(values))


def encode_raw03(
    disk: Disk,
    *,
    side: int,
    encoding: RawEncoding = RawEncoding.ERA_B,
) -> bytes:
    if not 0 <= side < disk.side_count:
        message = f"the image has no side {side}"
        raise ValueError(message)

    return encode_block_stream(
        [block.payload for block in disk.sides[side].blocks],
        encoding=encoding,
    )


def _write_value(bit: int, following: int) -> int:
    if bit:
        return WRITE_BIT_ONE
    return WRITE_ZERO_THEN_ONE if following else WRITE_ZERO_THEN_ZERO


def encode_write_block(framed: bytes) -> bytes:
    values = bytearray()
    for index, byte in enumerate(framed):
        following = framed[(index + 1) % len(framed)]
        values += bytes(
            _write_value((byte >> bit) & 1, (byte >> (bit - 1)) & 1) for bit in range(7, 3, -1)
        )
        values += bytes(
            _write_value(
                (following >> bit) & 1,
                (following >> (bit - 1)) & 1 if bit else (byte >> 7) & 1,
            )
            for bit in range(3, -1, -1)
        )
    return bytes(values)


def encode_write_stream(payloads: Sequence[bytes]) -> bytes:
    stream = bytearray(WRITE_HEADER + bytes([WRITE_GAP_BYTE]) * WRITE_LEAD_IN_BYTES)
    for index, payload in enumerate(payloads):
        if index:
            stream += bytes([WRITE_GAP_BYTE]) * WRITE_GAP_BYTES
        framed = bytes([SYNC_MARK]) + payload + encode_crc(block_crc(payload))
        stream += pack_raw03(encode_write_block(framed))
    short = -len(stream) % WRITE_PACKET_BYTES
    return bytes(stream + bytes([WRITE_GAP_BYTE]) * short)


def _nibble(values: bytes) -> int:
    return sum(
        (value == WRITE_BIT_ONE) << (NIBBLE_BITS - 1 - index) for index, value in enumerate(values)
    )


def _unframe(values: bytes, size: int) -> bytes:
    chunks = [values[start : start + NIBBLE_BITS] for start in range(0, len(values), NIBBLE_BITS)]
    return bytes(
        (_nibble(chunks[2 * index]) << NIBBLE_BITS) | _nibble(chunks[2 * index - 1])
        for index in range(size)
    )


def _block_size(kind: int, pending: int) -> int:
    length = _expected_length(kind, pending)
    if length is None:
        message = f"a written block has kind {kind:#04x}, which no side carries"
        raise ValueError(message)
    return length


def decode_write_stream(stream: bytes) -> tuple[bytes, ...]:
    if not stream.startswith(WRITE_HEADER):
        message = "the stream does not start with the write header"
        raise ValueError(message)
    cursor = len(WRITE_HEADER) + WRITE_LEAD_IN_BYTES
    payloads: list[bytes] = []
    pending = 0
    while stream[cursor:].strip(bytes([WRITE_GAP_BYTE])):
        kind = _unframe(unpack_raw03(stream[cursor : cursor + NIBBLE_BITS]), 2)[1]
        size = 1 + _block_size(kind, pending) + CRC_SIZE
        framed = _unframe(unpack_raw03(stream[cursor : cursor + 2 * size]), size)
        payload = framed[1 : size - CRC_SIZE]
        if decode_crc(framed[size - CRC_SIZE :]) != block_crc(payload):
            message = (
                f"a written block of kind {kind:#04x} carries a checksum its data does not match"
            )
            raise ValueError(message)
        if kind == BlockKind.FILE_HEADER:
            pending = FileHeader.parse(payload).size
        payloads.append(payload)
        cursor += 2 * size + WRITE_GAP_BYTES
    return tuple(payloads)


def _diagnostic(code: str, severity: Severity, detail: dict[str, object]) -> Diagnostic:
    return Diagnostic(code=code, severity=severity, message=CODES[code], detail=detail)


def _gap_end(values: bytes, start: int) -> int | None:
    zeros = 0
    for index in range(start, len(values)):
        value = values[index]
        if value == GAP_VALUE:
            zeros += 1
            continue
        if value == SYNC_VALUE and zeros >= MIN_GAP_VALUES:
            return index
        zeros = 0
    return None


def lead_in_bits(values: bytes) -> int | None:
    sync = _gap_end(values, 0)
    if sync is None:
        return None
    return sync - len(values[:sync].rstrip(bytes([GAP_VALUE])))


def _decode_region(values: bytes, start: int, pending: int) -> tuple[bytes, int, int | None]:
    bits: list[int] = []
    previous = 1
    index = start
    needed: int | None = None

    while index < len(values):
        value = values[index]
        index += 1
        key = (previous << 4) | value
        if key == KEY_ONE_ONE:
            bits += [0, 0]
            previous = 0
        elif key == KEY_ZERO_ZERO:
            bits.append(0)
            previous = 0
        elif key == KEY_ONE_TWO:
            bits += [0, 1]
            previous = 1
        elif key in (KEY_ZERO_ONE, KEY_ONE_ZERO):
            bits.append(1)
            previous = 1
        else:
            bits.append(0)
            previous = 0

        if needed is None and len(bits) >= HEADER_BITS:
            kind = sum(
                bit << position for position, bit in enumerate(bits[BITS_PER_BYTE:HEADER_BITS])
            )
            length = _expected_length(kind, pending)
            if length is None:
                return _pack_bits(bits), index, None
            needed = 1 + length + CRC_SIZE
        if needed is not None and len(bits) >= needed * BITS_PER_BYTE:
            break

    return _pack_bits(bits), index, needed


def _pack_bits(bits: list[int]) -> bytes:
    out = bytearray(len(bits) // BITS_PER_BYTE)
    for position, bit in enumerate(bits[: len(out) * BITS_PER_BYTE]):
        if bit:
            out[position // BITS_PER_BYTE] |= 1 << (position % BITS_PER_BYTE)
    return bytes(out)


def _expected_length(kind: int, pending: int) -> int | None:
    if kind == BlockKind.DISK_INFO:
        return DISK_INFO_SIZE
    if kind == BlockKind.FILE_AMOUNT:
        return FILE_AMOUNT_SIZE
    if kind == BlockKind.FILE_HEADER:
        return FILE_HEADER_SIZE
    if kind == BlockKind.FILE_DATA:
        return 1 + pending
    return None


def _only_gap(rest: bytes) -> bool:
    return len(set(rest)) <= 1 and set(rest) <= GAP_BYTES


def _bounded_by_crc(values: bytes, gap: int) -> tuple[bytes, int, int] | None:
    following = _gap_end(values, gap + 1)
    end = len(values) if following is None else following
    region, _, _ = _decode_region(values[:end], gap, len(values))
    body = region[1:]

    def ends_at_gap(size: int) -> bool:
        return _only_gap(body[size + CRC_SIZE :])

    size = crc_boundary(body, range(1, len(body) - CRC_SIZE + 1), ends_at_gap)
    if size is None:
        return None
    resume = len(values) if following is None else following - MIN_GAP_VALUES
    return body[:size], decode_crc(body[size : size + CRC_SIZE]), resume


def decode_raw03(values: bytes) -> tuple[Side, tuple[Diagnostic, ...]]:
    side, findings, _ = _walk(values)
    return side, findings


def block_starts(values: bytes) -> tuple[int, ...]:
    return tuple(start for start, _ in block_regions(values))


def block_regions(values: bytes) -> tuple[tuple[int, int], ...]:
    _, _, regions = _walk(values)
    return regions


def _short_gap(gap: int, previous_end: int, *, block: int) -> tuple[Diagnostic, ...]:
    bits = gap - previous_end
    if not block or bits >= ADAPTER_BLIND_BITS:
        return ()
    detail: dict[str, object] = {"offset": gap, "bits": bits, "block": block}
    return (_diagnostic("FDS017", Severity.WARNING, detail),)


def _past_declared(blocks: Sequence[Block]) -> bool:
    amounts = [block for block in blocks if block.kind is BlockKind.FILE_AMOUNT]
    return bool(amounts) and len(blocks) >= declared_blocks(amounts[0].payload)


def _lost_region(gap: int, blocks: Sequence[Block]) -> Diagnostic:
    detail: dict[str, object] = {"offset": gap, "block": len(blocks)}
    if _past_declared(blocks):
        return _diagnostic("FDS018", Severity.INFO, detail)
    return _diagnostic("FDS015", Severity.WARNING, detail)


def _walk(values: bytes) -> tuple[Side, tuple[Diagnostic, ...], tuple[tuple[int, int], ...]]:
    findings: list[Diagnostic] = []
    blocks: list[Block] = []
    regions: list[tuple[int, int]] = []
    cursor = 0
    pending = 0

    while cursor < len(values):
        gap = _gap_end(values, cursor)
        if gap is None:
            break
        findings.extend(_short_gap(gap, cursor, block=len(blocks)))
        data, cursor, needed = _decode_region(values, gap, pending)
        if not data or data[0] != SYNC_MARK or needed is None:
            findings.append(_lost_region(gap, blocks))
            continue
        body = data[1:]
        length = needed - 1 - CRC_SIZE
        if len(body) < length + CRC_SIZE:
            findings.append(
                _diagnostic(
                    "FDS004",
                    Severity.ERROR,
                    {"offset": gap, "recovered": len(body), "block": len(blocks)},
                ),
            )
            continue
        payload = body[:length]
        stored = decode_crc(body[length : length + CRC_SIZE])
        if payload[0] == BlockKind.FILE_DATA and stored != block_crc(payload):
            found = _bounded_by_crc(values, gap)
            if found is not None:
                payload, stored, cursor = found
                findings.append(
                    _diagnostic(
                        "FDS016",
                        Severity.WARNING,
                        {"offset": gap, "declared": length - 1, "actual": len(payload) - 1},
                    ),
                )
        block = Block(kind=BlockKind(payload[0]), payload=payload, stored_crc=stored)
        if stored != block_crc(payload):
            findings.append(
                _diagnostic(
                    "FDS002",
                    Severity.ERROR,
                    {"stored": stored, "computed": block.computed_crc},
                ),
            )
        if block.kind is BlockKind.FILE_HEADER:
            pending = FileHeader.parse(payload).size
        blocks.append(block)
        regions.append((gap, cursor))

    if not blocks:
        findings.append(_diagnostic("FDS014", Severity.ERROR, {"values": len(values)}))

    return Side(blocks=tuple(blocks), tail=b"", capacity=0), tuple(findings), tuple(regions)
