from __future__ import annotations

import os
from datetime import date
from typing import Final

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.core.diskinfo import FIELDS_BY_NAME, SERIAL_ORDER, SHOWA_EPOCH, to_bcd
from fdstoolkit.core.showa import LAST_YEAR_COUNT, ShowaDateError, encode_date, parse_date

KIOSK_SERIAL_ENV: Final = "FDSTOOLKIT_KIOSK_SERIAL"
SERIAL_DIGITS: Final = 4
SERIAL_BASE: Final = 16
LOWEST_SERIAL: Final = 0x0001
HIGHEST_SERIAL: Final = 0xFFFE
MAX_REWRITES: Final = 99
NO_SERIAL: Final = (
    "a kiosk rewrite stamps a Disk Writer serial, and none is configured: set "
    f"{KIOSK_SERIAL_ENV} to four hexadecimal digits, such as 0123"
)


class KioskError(ValueError):
    pass


def kiosk_serial() -> int:
    raw = os.environ.get(KIOSK_SERIAL_ENV, "").strip()
    if not raw:
        raise KioskError(NO_SERIAL)
    bad = KioskError(
        f"{KIOSK_SERIAL_ENV} is {raw!r}, and a Disk Writer serial is four hexadecimal digits "
        f"from {LOWEST_SERIAL:04X} to {HIGHEST_SERIAL:04X}"
    )
    try:
        value = int(raw, SERIAL_BASE)
    except ValueError as error:
        raise bad from error
    if len(raw) != SERIAL_DIGITS or not LOWEST_SERIAL <= value <= HIGHEST_SERIAL:
        raise bad
    return value


def _stamp_date(rewrite_date: str | None, today: date) -> tuple[int, int, int]:
    if rewrite_date is not None:
        try:
            return parse_date(rewrite_date, field="the rewrite date")
        except ShowaDateError as error:
            raise KioskError(str(error)) from error
    try:
        return parse_date(today.isoformat(), field="today")
    except ShowaDateError as error:
        message = (
            f"today, {today.isoformat()}, is past {SHOWA_EPOCH + LAST_YEAR_COUNT}, the last year "
            "a disk date can hold; pass --rewrite-date with a date a kiosk could have stamped"
        )
        raise KioskError(message) from error


def _with_field(payload: bytes, name: str, value: bytes) -> bytes:
    field = FIELDS_BY_NAME[name]
    return payload[: field.offset] + value + payload[field.offset + field.length :]


def _stamped(index: int, side: Side, serial: int, stamp: tuple[int, int, int]) -> Side:
    info = side.disk_info
    if info is None:
        return side
    count = info.rewrite_count or 0
    if count >= MAX_REWRITES:
        message = f"side {index} has been rewritten {count} times, the most its count holds"
        raise KioskError(message)
    payload = _with_field(info.payload, "rewrite_count", bytes([to_bcd(count + 1)]))
    payload = _with_field(payload, "rewritten_date", encode_date(*stamp))
    payload = _with_field(payload, "writer_serial", serial.to_bytes(2, SERIAL_ORDER))
    first = Block(kind=BlockKind.DISK_INFO, payload=payload)
    return Side(blocks=(first, *side.blocks[1:]), tail=side.tail, capacity=side.capacity)


def kiosk_target(disk: Disk, *, rewrite_date: str | None, today: date) -> Disk:
    serial = kiosk_serial()
    stamp = _stamp_date(rewrite_date, today)
    sides = tuple(_stamped(index, side, serial, stamp) for index, side in enumerate(disk.sides))
    return Disk(sides=sides, header_side_count=disk.header_side_count)
