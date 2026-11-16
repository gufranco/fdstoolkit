from __future__ import annotations

from device import FakeFdsStick

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.disk import Disk
from fdstoolkit.hardware.fdsstick import (
    CHUNK_PAYLOAD,
    WRITE_PAYLOAD,
    FdsStick,
    HidApiTransport,
)

FLASH_REPORTS = frozenset({0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09})


EMULATOR_REPORTS = frozenset({0x21, 0x22, 0x23})


FINISH = bytes([0x20, 0x00])


WRITE_REPORT_LENGTH = 0x100


PACKETS_PAST_THE_WRAP = 300


FACTORY_FILL = bytes([0x75, 0x5D, 0xD7])


FILLS_PER_PACKET = 85


def raw_side(packets: int = PACKETS_PAST_THE_WRAP) -> bytes:
    return bytes(range(256)) * (packets * CHUNK_PAYLOAD // 256 + 1)


def stick_over(device: FakeFdsStick, pauses: list[float] | None = None) -> FdsStick:
    taken = pauses if pauses is not None else []
    return FdsStick(HidApiTransport(device), pause=taken.append)


def a_full_session() -> FakeFdsStick:
    device = FakeFdsStick(side=raw_side()[:CHUNK_PAYLOAD])
    stick = stick_over(device)
    stick.read_raw_side()
    stick.write_raw_side(bytes(WRITE_PAYLOAD))
    return device


def formatted(game: str) -> Disk:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name=game))
    return disk
