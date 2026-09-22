from __future__ import annotations

from typing import Final

HXC_SIGNATURE: Final = b"HXCQDDRV"
QDF_SIGNATURE: Final = b"-QD format-" + b"\xff" * 5
MZQ_SYNC: Final = b"\x00\x16\x16\xa5"
MZQ_MARK: Final = b"CRC"
MZQ_MARK_OFFSET: Final = 5


class ForeignImageError(ValueError):
    pass


def foreign_format(data: bytes) -> str | None:
    if data.startswith(HXC_SIGNATURE):
        return "an HxC Floppy Emulator flux image"
    if data.startswith(QDF_SIGNATURE):
        return "a Sharp MZ Quick Disk image in QDF form"
    marked = data[MZQ_MARK_OFFSET : MZQ_MARK_OFFSET + len(MZQ_MARK)] == MZQ_MARK
    if data.startswith(MZQ_SYNC) and marked:
        return "a Sharp MZ Quick Disk image in MZQ form"
    return None


def reject_foreign(data: bytes) -> None:
    found = foreign_format(data)
    if found is not None:
        message = f"this is {found}, not a Famicom Disk System image"
        raise ForeignImageError(message)
