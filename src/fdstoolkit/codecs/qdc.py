from __future__ import annotations

from typing import Final

QDC_COUNT_NS: Final = 400
ESCAPE: Final = 0x00
WIDE_COUNT: Final = 0x01
OVERFLOW: Final = 0x02
SPECIAL: Final = 0x00
DATA_START: Final = 0x00
DATA_END: Final = 0xFF
ESCAPE_SIZE: Final = 4
OVERFLOW_UNIT: Final = 65536
START_MARKER: Final = bytes([ESCAPE, SPECIAL, SPECIAL, DATA_START])


class QdcError(ValueError):
    pass


def is_qdc(data: bytes) -> bool:
    return data.startswith(START_MARKER)


def _escape(data: bytes, cursor: int) -> tuple[int, int]:
    if cursor + ESCAPE_SIZE > len(data):
        message = f"the QDC file ends inside an escape at byte {cursor}"
        raise QdcError(message)
    kind = data[cursor + 1]
    value = int.from_bytes(data[cursor + 2 : cursor + ESCAPE_SIZE], "little")
    if kind == SPECIAL:
        return kind, data[cursor + 3]
    if kind in (WIDE_COUNT, OVERFLOW):
        return kind, value
    message = f"the QDC file has an unknown escape 0x{kind:02X} at byte {cursor}"
    raise QdcError(message)


def _first_count(data: bytes) -> int:
    start = data.find(START_MARKER)
    return 0 if start < 0 else start + ESCAPE_SIZE


def qdc_counts(data: bytes) -> tuple[int, ...]:
    cursor = _first_count(data)
    counts: list[int] = []
    while cursor < len(data):
        byte = data[cursor]
        if byte != ESCAPE:
            counts.append(byte)
            cursor += 1
            continue
        kind, value = _escape(data, cursor)
        cursor += ESCAPE_SIZE
        if kind == SPECIAL and value == DATA_END:
            break
        if kind == WIDE_COUNT:
            counts.append(value)
        elif kind == OVERFLOW:
            counts[-1:] = [(counts[-1] if counts else 0) + value * OVERFLOW_UNIT]
    return tuple(counts)
