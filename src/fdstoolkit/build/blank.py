from __future__ import annotations

from typing import Final

from fdstoolkit.codecs.fds import SIDE_SIZE, build_header
from fdstoolkit.core.blocks import DISK_INFO_SIZE
from fdstoolkit.core.diskinfo import FIELDS_BY_NAME, VERIFICATION_STRING

MAX_SIDES: Final = 8
GAME_NAME_LENGTH: Final = 3
DEFAULT_GAME_NAME: Final = "   "
DEFAULT_LICENSEE: Final = 0x00
COUNTRY_JAPAN: Final = 0x49
FILLER_BYTE: Final = 0xFF
UNWRITTEN_BYTE: Final = 0xFF

FACTORY_CONSTANTS: Final[dict[str, bytes]] = {
    "game_type": bytes([0x20]),
    "unknown_18": bytes([0x00]),
    "filler_1a": bytes([FILLER_BYTE] * 5),
    "country": bytes([COUNTRY_JAPAN]),
    "unknown_23": bytes([0x61]),
    "unknown_24": bytes([0x00]),
    "unknown_25": bytes([0x00, 0x02]),
    "unknown_27": bytes([0x00, 0xFF, 0xFF, 0xFF, 0x00]),
    "rewritten_date": bytes([UNWRITTEN_BYTE] * 3),
    "unknown_2f": bytes([UNWRITTEN_BYTE]),
    "unknown_30": bytes([UNWRITTEN_BYTE]),
    "writer_serial": bytes([UNWRITTEN_BYTE] * 2),
    "unknown_33": bytes([UNWRITTEN_BYTE]),
    "rewrite_count": bytes([0x00]),
    "actual_side": bytes([0x00]),
    "disk_type_other": bytes([0x00]),
    "disk_version": bytes([0x00]),
}

REFERENCE_BLANK_64_SHA256: Final = (
    "021c40c7962f1395bf3ad70273264bdc4bf5cd98b212409d0551f7c5f1042776"
)
REFERENCE_BLANK_128_SHA256: Final = (
    "e6dd229af11a153ddefc50f18431a509d1890f9b39b8349f6108c3e29315bccc"
)


def _write(payload: bytearray, name: str, value: bytes) -> None:
    field = FIELDS_BY_NAME[name]
    payload[field.offset : field.offset + field.length] = value


def disk_info_block(*, side: int, disk_number: int, game_name: str) -> bytes:
    payload = bytearray(DISK_INFO_SIZE)
    _write(payload, "block_code", bytes([0x01]))
    _write(payload, "verification", VERIFICATION_STRING)
    _write(payload, "licensee", bytes([DEFAULT_LICENSEE]))
    _write(payload, "game_name", game_name.encode("ascii"))
    _write(payload, "side", bytes([side]))
    _write(payload, "disk_number", bytes([disk_number]))
    for name, value in FACTORY_CONSTANTS.items():
        _write(payload, name, value)
    return bytes(payload)


def formatted_side(*, side: int, disk_number: int, game_name: str) -> bytes:
    content = disk_info_block(side=side, disk_number=disk_number, game_name=game_name)
    content += bytes([0x02, 0x00])
    return content.ljust(SIDE_SIZE, b"\0")


def blank_image(
    *,
    sides: int,
    headered: bool,
    formatted: bool,
    game_name: str = DEFAULT_GAME_NAME,
) -> bytes:
    if not 1 <= sides <= MAX_SIDES:
        message = f"a blank disk has between 1 and {MAX_SIDES} sides, got {sides}"
        raise ValueError(message)
    if len(game_name) != GAME_NAME_LENGTH:
        message = f"a game name is exactly three characters, got {len(game_name)}"
        raise ValueError(message)

    out = bytearray()
    if headered:
        out += build_header(sides)
    for index in range(sides):
        if formatted:
            out += formatted_side(
                side=index % 2,
                disk_number=index // 2,
                game_name=game_name,
            )
        else:
            out += bytes(SIDE_SIZE)
    return bytes(out)
