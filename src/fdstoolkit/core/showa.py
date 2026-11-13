from __future__ import annotations

import re
from datetime import date
from typing import Final

from fdstoolkit.core.diskinfo import SHOWA_EPOCH, to_bcd

DATE_PATTERN: Final = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
LAST_YEAR_COUNT: Final = 99


class ShowaDateError(ValueError):
    pass


def parse_date(text: str, *, field: str) -> tuple[int, int, int]:
    match = DATE_PATTERN.match(text)
    if match is None:
        message = f"{field} is written YYYY-MM-DD, got {text}"
        raise ShowaDateError(message)
    year, month, day = (int(part) for part in match.groups())
    shown = f"{year:04}-{month:02}-{day:02}"
    try:
        date(year, month, day)
    except ValueError as error:
        message = f"{field} {shown} is not a day on the calendar"
        raise ShowaDateError(message) from error
    if not 0 <= year - SHOWA_EPOCH <= LAST_YEAR_COUNT:
        message = (
            f"{field} {shown} is outside {SHOWA_EPOCH} to {SHOWA_EPOCH + LAST_YEAR_COUNT}, "
            "the years the two BCD digits of a disk date can hold"
        )
        raise ShowaDateError(message)
    return year, month, day


def encode_date(year: int, month: int, day: int) -> bytes:
    return bytes([to_bcd(year - SHOWA_EPOCH), to_bcd(month), to_bcd(day)])
