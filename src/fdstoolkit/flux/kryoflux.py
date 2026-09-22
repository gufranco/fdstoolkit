from __future__ import annotations

from typing import Final

from fdstoolkit.flux.model import (
    NS_PER_SECOND,
    FluxCapture,
    FluxTrack,
    Revolution,
    Source,
    flag_partial,
)

MASTER_CLOCK_HZ: Final = ((18_432_000 * 73) / 14) / 2
SAMPLE_CLOCK_HZ: Final = MASTER_CLOCK_HZ / 2
INDEX_CLOCK_HZ: Final = MASTER_CLOCK_HZ / 16

FLUX2_TOP: Final = 0x07
NOP1: Final = 0x08
NOP2: Final = 0x09
NOP3: Final = 0x0A
OVL16: Final = 0x0B
FLUX3: Final = 0x0C
OOB: Final = 0x0D
OVERFLOW: Final = 0x10000

OOB_INVALID: Final = 0x00
OOB_STREAM_INFO: Final = 0x01
OOB_INDEX: Final = 0x02
OOB_STREAM_END: Final = 0x03
OOB_KF_INFO: Final = 0x04
OOB_EOF: Final = 0x0D

OOB_HEADER_SIZE: Final = 4


def ticks_to_ns(ticks: int) -> int:
    return round(ticks * NS_PER_SECOND / SAMPLE_CLOCK_HZ)


def is_kryoflux(data: bytes) -> bool:
    return bool(data) and data[0] == OOB and len(data) >= OOB_HEADER_SIZE


SKIP: Final = {NOP1: 1, NOP2: 2, NOP3: 3}


def _cell(data: bytes, cursor: int) -> tuple[int | None, int, int]:
    head = data[cursor]
    if head <= FLUX2_TOP:
        return _wide(data, cursor, 2, cursor, cursor + 1)
    skip = SKIP.get(head)
    if skip is not None:
        return None, cursor + skip, 0
    if head == OVL16:
        return None, cursor + 1, OVERFLOW
    if head == FLUX3:
        return _wide(data, cursor, 3, cursor + 1, cursor + 2)
    return head, cursor + 1, 0


def _wide(data: bytes, cursor: int, width: int, high: int, low: int) -> tuple[int | None, int, int]:
    if cursor + width > len(data):
        return None, len(data), 0
    return (data[high] << 8) | data[low], cursor + width, 0


def read_stream(data: bytes, *, track: int = 0) -> FluxCapture:
    closed: list[list[int]] = []
    current: list[int] = []
    carry = 0
    cursor = 0

    while cursor < len(data):
        head = data[cursor]
        if head == OOB:
            if cursor + OOB_HEADER_SIZE > len(data):
                break
            kind = data[cursor + 1]
            if kind == OOB_EOF:
                break
            size = int.from_bytes(data[cursor + 2 : cursor + 4], "little")
            if kind == OOB_INDEX and current:
                closed.append(current)
                current = []
            cursor += OOB_HEADER_SIZE + size
            continue

        value, cursor, overflow = _cell(data, cursor)
        if overflow:
            carry += overflow
            continue
        if value is None:
            continue
        current.append(ticks_to_ns(carry + value))
        carry = 0

    spins = [Revolution(intervals=tuple(values)) for values in closed]
    if current:
        spins.append(Revolution(intervals=tuple(current), complete=False))
    if not spins:
        message = "the stream carries no flux cell"
        raise ValueError(message)

    return FluxCapture(
        source=Source.KRYOFLUX,
        tracks=(FluxTrack(index=track, revolutions=flag_partial(spins)),),
        sample_ns=NS_PER_SECOND / SAMPLE_CLOCK_HZ,
    )
