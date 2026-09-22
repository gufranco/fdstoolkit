from __future__ import annotations

from enum import StrEnum

from fdstk.patch.build import build_ips
from fdstk.patch.formats import PatchError, PatchFormat, apply_ips, detect_format


class SaveFormat(StrEnum):
    IPS = "ips"
    IMAGE = "image"
    UNKNOWN = "unknown"


def detect_save_format(save: bytes) -> SaveFormat:
    if detect_format(save) is PatchFormat.IPS:
        return SaveFormat.IPS
    if len(save) and len(save) % 65500 in (0, 16):
        return SaveFormat.IMAGE
    return SaveFormat.UNKNOWN


def merge_save(image: bytes, save: bytes) -> bytes:
    kind = detect_save_format(save)
    if kind is SaveFormat.IPS:
        return apply_ips(save, image)
    if kind is SaveFormat.IMAGE:
        if len(save) != len(image):
            message = (
                f"the save is {len(save)} bytes and the image is {len(image)}, "
                "so it does not match this disk"
            )
            raise PatchError(message)
        return save
    message = "not a save this toolkit recognises, expected an IPS patch or a whole image"
    raise PatchError(message)


def extract_save(
    original: bytes,
    played: bytes,
    *,
    fmt: SaveFormat = SaveFormat.IPS,
) -> bytes:
    if fmt is SaveFormat.IPS:
        return build_ips(original, played)
    if fmt is SaveFormat.IMAGE:
        return played
    message = "cannot write a save in an unknown format"
    raise PatchError(message)
