from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final

from fdstoolkit.build.blank import blank_image

EVERDRIVE_ROOT: Final = "EDN8/gamedata"
EVERDRIVE_SAVE_NAME: Final = "bram.srm"
BACKUP_SUFFIX: Final = ".bak"
CARD_SUFFIX: Final = ".fds"


class FirmwareVariant(StrEnum):
    RELEASED = "released"
    MASTER = "master"


def firmware_checksum(firmware: bytes) -> str:
    return hashlib.md5(firmware, usedforsecurity=False).hexdigest()


def everdrive_save_path(name: str) -> str:
    stem = PurePosixPath(name)
    folder = stem.name if stem.suffix.lower() == CARD_SUFFIX else f"{stem.name}{CARD_SUFFIX}"
    return str(PurePosixPath(EVERDRIVE_ROOT) / folder / EVERDRIVE_SAVE_NAME)


def backup_name(name: str) -> str:
    return f"{name}{BACKUP_SUFFIX}"


def card_blank(*, sides: int, variant: FirmwareVariant = FirmwareVariant.MASTER) -> bytes:
    if variant is FirmwareVariant.RELEASED:
        return blank_image(sides=sides, headered=False, formatted=False)
    return blank_image(sides=sides, headered=False, formatted=True)
