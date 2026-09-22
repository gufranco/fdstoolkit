from __future__ import annotations

from enum import StrEnum
from typing import Final

from fdstk.codecs.fds import HEADER_SIZE, has_header
from fdstk.patch.build import build_ips, build_ups
from fdstk.patch.formats import (
    PatchError,
    PatchFormat,
    apply_bps,
    apply_ips,
    apply_ups,
    detect_format,
)

SIDE_SIZE: Final = 65500


class SaveFormat(StrEnum):
    IPS = "ips"
    UPS = "ups"
    BPS = "bps"
    IMAGE = "image"
    UNKNOWN = "unknown"


PATCH_SAVES: Final[dict[PatchFormat, SaveFormat]] = {
    PatchFormat.IPS: SaveFormat.IPS,
    PatchFormat.UPS: SaveFormat.UPS,
    PatchFormat.BPS: SaveFormat.BPS,
}


def detect_save_format(save: bytes) -> SaveFormat:
    patch = PATCH_SAVES.get(detect_format(save))
    if patch is not None:
        return patch
    if len(save) and len(save) % SIDE_SIZE in (0, HEADER_SIZE):
        return SaveFormat.IMAGE
    return SaveFormat.UNKNOWN


def _body(data: bytes) -> bytes:
    return data[HEADER_SIZE:] if has_header(data) else data


def _merge_image(image: bytes, save: bytes) -> bytes:
    if len(_body(save)) != len(_body(image)):
        message = (
            f"the save holds {len(_body(save))} bytes of disk and the image holds "
            f"{len(_body(image))}, so it does not match this disk"
        )
        raise PatchError(message)
    header = image[:HEADER_SIZE] if has_header(image) else b""
    return header + _body(save)


def merge_save(image: bytes, save: bytes) -> bytes:
    kind = detect_save_format(save)
    if kind is SaveFormat.IPS:
        return apply_ips(save, image)
    if kind is SaveFormat.UPS:
        return apply_ups(save, image)
    if kind is SaveFormat.BPS:
        return apply_bps(save, image)
    if kind is SaveFormat.IMAGE:
        return _merge_image(image, save)
    message = "not a save this toolkit recognises, expected IPS, UPS, BPS or a whole image"
    raise PatchError(message)


def extract_save(
    original: bytes,
    played: bytes,
    *,
    fmt: SaveFormat = SaveFormat.IPS,
) -> bytes:
    if fmt is SaveFormat.IPS:
        return build_ips(original, played)
    if fmt is SaveFormat.UPS:
        return build_ups(original, played)
    if fmt is SaveFormat.IMAGE:
        return played
    message = f"cannot write a save as {fmt}"
    raise PatchError(message)
