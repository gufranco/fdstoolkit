from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

from fdstoolkit.core.bitstream import BITS_PER_BYTE, GAP_BITS, LEAD_IN_BITS
from fdstoolkit.core.blocks import (
    DISK_INFO_SIZE,
    FILE_AMOUNT_SIZE,
    FILE_HEADER_SIZE,
    TEST_BLOCK_CODE,
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
ADAPTER_BLIND_BITS: Final = 488
GAP_BYTES: Final = frozenset({0x00, 0xFF})
SYNC_MARK: Final = 0x80
MARK_GAP_BITS: Final = SYNC_MARK.bit_length() - 1
KEY_ONE_ONE: Final = 0x11
KEY_ZERO_ZERO: Final = 0x00
KEY_ONE_TWO: Final = 0x12
KEY_ZERO_ONE: Final = 0x01
KEY_ONE_ZERO: Final = 0x10
HEADER_BITS: Final = 16

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


def encode_bits(bits: Sequence[int]) -> bytes:
    out = bytearray()
    previous = 0
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
    return encode_bits(_bits_lsb_first(data))


def block_pulses(payload: bytes) -> bytes:
    framed = bytes([SYNC_MARK]) + payload + encode_crc(block_crc(payload))
    return encode_era_b(framed)[MARK_GAP_BITS:]


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
    values = bytearray(bytes([GAP_VALUE]) * (LEAD_IN_BITS - MARK_GAP_BITS))

    for index, payload in enumerate(payloads):
        if index:
            values += bytes([GAP_VALUE]) * (GAP_BITS - MARK_GAP_BITS)
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
    regions = block_regions(values)
    if not regions:
        return None
    start, _ = regions[0]
    return start - len(values[:start].rstrip(bytes([GAP_VALUE])))


DECODED: Final[dict[int, tuple[tuple[int, ...], int]]] = {
    KEY_ONE_ONE: ((0, 0), 0),
    KEY_ZERO_ZERO: ((0,), 0),
    KEY_ONE_TWO: ((0, 1), 1),
    KEY_ZERO_ONE: ((1,), 1),
    KEY_ONE_ZERO: ((1,), 1),
}
UNCLASSED: Final = ((0,), 0)


def _kind_of(bits: list[int]) -> int:
    return sum(bit << position for position, bit in enumerate(bits[BITS_PER_BYTE:HEADER_BITS]))


def _decode_region(values: bytes, start: int, pending: int) -> tuple[bytes, int, int | None]:
    bits: list[int] = [0] * MARK_GAP_BITS
    previous = 0
    index = start
    needed: int | None = None
    while index < len(values) and (needed is None or len(bits) < needed * BITS_PER_BYTE):
        added, previous = DECODED.get((previous << 4) | values[index], UNCLASSED)
        bits += added
        index += 1
        if needed is None and len(bits) >= HEADER_BITS:
            length = expected_length(_kind_of(bits), pending)
            if length is None:
                return _pack_bits(bits), index, None
            needed = 1 + length + CRC_SIZE
    return _pack_bits(bits), index, needed


def _pack_bits(bits: list[int]) -> bytes:
    out = bytearray(len(bits) // BITS_PER_BYTE)
    for position, bit in enumerate(bits[: len(out) * BITS_PER_BYTE]):
        if bit:
            out[position // BITS_PER_BYTE] |= 1 << (position % BITS_PER_BYTE)
    return bytes(out)


def expected_length(kind: int, pending: int) -> int | None:
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


def _lost_region(gap: int, blocks: Sequence[Block], data: bytes) -> Diagnostic:
    detail: dict[str, object] = {"offset": gap, "block": len(blocks)}
    if data[:2] == bytes([SYNC_MARK, TEST_BLOCK_CODE]):
        return _diagnostic("FDS020", Severity.INFO, detail)
    if _past_declared(blocks):
        return _diagnostic("FDS018", Severity.INFO, detail)
    return _diagnostic("FDS015", Severity.WARNING, detail)


def _gap_start(values: bytes, sync: int) -> int:
    start = sync
    while start > 0 and values[start - 1] == GAP_VALUE:
        start -= 1
    return start


def _clean_payload_at(values: bytes, gap: int, pending: int) -> bytes | None:
    data, _, needed = _decode_region(values, gap, pending)
    if not data or data[0] != SYNC_MARK or needed is None or len(data) < needed:
        return None
    body = data[1:needed]
    payload = body[:-CRC_SIZE]
    return payload if decode_crc(body[-CRC_SIZE:]) == block_crc(payload) else None


def _clean_block_at(values: bytes, gap: int, pending: int) -> bool:
    return _clean_payload_at(values, gap, pending) is not None


def _side_start(values: bytes) -> int:
    gap = _gap_end(values, 0)
    while gap is not None:
        payload = _clean_payload_at(values, gap, 0)
        if payload is not None and payload[0] == BlockKind.DISK_INFO:
            return _gap_start(values, gap)
        gap = _gap_end(values, gap + 1)
    return 0


def _resume_after_failure(values: bytes, start: int, cursor: int, pending: int) -> int:
    gap = _gap_end(values, start + 1)
    if gap is None or gap >= cursor or not _clean_block_at(values, gap, pending):
        return cursor
    return _gap_start(values, gap)


@dataclass(frozen=True, slots=True)
class _PulseWalk:
    blocks: tuple[Block, ...]
    findings: tuple[Diagnostic, ...]
    regions: tuple[tuple[int, int], ...]
    cursor: int
    pending: int
    done: bool = False


@dataclass(frozen=True, slots=True)
class _Framing:
    payload: bytes
    stored: int
    cursor: int
    findings: tuple[Diagnostic, ...]


def _noted(walk: _PulseWalk, cursor: int, findings: tuple[Diagnostic, ...]) -> _PulseWalk:
    return replace(walk, cursor=cursor, findings=(*walk.findings, *findings))


def _rebounded(values: bytes, gap: int, framing: _Framing) -> _Framing:
    payload = framing.payload
    if payload[0] != BlockKind.FILE_DATA or framing.stored == block_crc(payload):
        return framing
    found = _bounded_by_crc(values, gap)
    if found is None:
        return framing
    bounded, stored, cursor = found
    detail: dict[str, object] = {
        "offset": gap,
        "declared": len(payload) - 1,
        "actual": len(bounded) - 1,
    }
    finding = _diagnostic("FDS016", Severity.WARNING, detail)
    return _Framing(bounded, stored, cursor, (*framing.findings, finding))


def _framed(values: bytes, walk: _PulseWalk, gap: int, framing: _Framing) -> _PulseWalk:
    settled = _rebounded(values, gap, framing)
    payload, stored, cursor = settled.payload, settled.stored, settled.cursor
    block = Block(kind=BlockKind(payload[0]), payload=payload, stored_crc=stored)
    header = block.kind is BlockKind.FILE_HEADER
    pending = FileHeader.parse(payload).size if header else walk.pending
    failed = stored != block_crc(payload)
    detail: dict[str, object] = {"stored": stored, "computed": block.computed_crc}
    crc = (_diagnostic("FDS002", Severity.ERROR, detail),) if failed else ()
    return replace(
        walk,
        blocks=(*walk.blocks, block),
        regions=(*walk.regions, (gap, cursor)),
        findings=(*walk.findings, *settled.findings, *crc),
        cursor=_resume_after_failure(values, gap, cursor, pending) if failed else cursor,
        pending=pending,
    )


def _pulse_step(values: bytes, walk: _PulseWalk) -> _PulseWalk:
    gap = _gap_end(values, walk.cursor)
    if gap is None:
        return replace(walk, done=True)
    short = _short_gap(gap, walk.cursor, block=len(walk.blocks))
    data, cursor, needed = _decode_region(values, gap, walk.pending)
    if not data or data[0] != SYNC_MARK or needed is None:
        return _noted(walk, cursor, (*short, _lost_region(gap, walk.blocks, data)))
    body = data[1:]
    length = needed - 1 - CRC_SIZE
    if len(body) < length + CRC_SIZE:
        detail: dict[str, object] = {
            "offset": gap,
            "recovered": len(body),
            "block": len(walk.blocks),
        }
        return _noted(walk, cursor, (*short, _diagnostic("FDS004", Severity.ERROR, detail)))
    stored = decode_crc(body[length : length + CRC_SIZE])
    return _framed(values, walk, gap, _Framing(body[:length], stored, cursor, short))


def _walk(values: bytes) -> tuple[Side, tuple[Diagnostic, ...], tuple[tuple[int, int], ...]]:
    walk = _PulseWalk(blocks=(), findings=(), regions=(), cursor=_side_start(values), pending=0)
    while not walk.done and walk.cursor < len(values):
        walk = _pulse_step(values, walk)
    nothing = (_diagnostic("FDS014", Severity.ERROR, {"values": len(values)}),)
    findings = walk.findings if walk.blocks else (*walk.findings, *nothing)
    return Side(blocks=walk.blocks, tail=b"", capacity=0), findings, walk.regions
