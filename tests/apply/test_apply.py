from __future__ import annotations

import zlib

import pytest

from fdstk.build.blank import blank_image
from fdstk.codecs.fds import HEADER_SIZE, has_header
from fdstk.patch.apply import PatchOutcome, apply_patch
from fdstk.patch.formats import PatchError, PatchFormat, write_varint


def ips_setting(offset: int, payload: bytes) -> bytes:
    return b"PATCH" + offset.to_bytes(3, "big") + len(payload).to_bytes(2, "big") + payload + b"EOF"


def bps_replacing(source: bytes, target: bytes) -> bytes:
    body = bytearray()
    body += write_varint(len(source))
    body += write_varint(len(target))
    body += write_varint(0)
    body += write_varint(((len(target) - 1) << 2) | 1)
    body += target

    out = bytearray(b"BPS1")
    out += body
    out += zlib.crc32(source).to_bytes(4, "little")
    out += zlib.crc32(target).to_bytes(4, "little")
    out += zlib.crc32(bytes(out)).to_bytes(4, "little")
    return bytes(out)


def headerless() -> bytes:
    return blank_image(sides=1, headered=False, formatted=True, game_name="SMB")


def headered() -> bytes:
    return blank_image(sides=1, headered=True, formatted=True, game_name="SMB")


def test_an_ips_patch_applies_to_a_headerless_image() -> None:
    outcome = apply_patch(ips_setting(0x10, b"ZEL"), headerless())

    assert outcome.format is PatchFormat.IPS
    assert outcome.data[0x10:0x13] == b"ZEL"
    assert outcome.applied_to == "image"


def test_a_bps_patch_made_for_the_headerless_image_still_applies_to_a_headered_one() -> None:
    target = bytearray(headerless())
    target[0x10:0x13] = b"ZEL"
    patch = bps_replacing(headerless(), bytes(target))

    outcome = apply_patch(patch, headered())

    assert outcome.applied_to == "headerless image"
    assert outcome.header_restored
    assert has_header(outcome.data)
    assert outcome.data[HEADER_SIZE + 0x10 : HEADER_SIZE + 0x13] == b"ZEL"


def test_a_bps_patch_made_for_the_headered_image_applies_directly() -> None:
    target = bytearray(headered())
    target[HEADER_SIZE + 0x10 : HEADER_SIZE + 0x13] = b"ZEL"
    patch = bps_replacing(headered(), bytes(target))

    outcome = apply_patch(patch, headered())

    assert outcome.applied_to == "image"
    assert not outcome.header_restored


def test_a_patch_that_matches_neither_form_is_reported() -> None:
    patch = bps_replacing(bytes([0x01, 0x02]), bytes([0x03, 0x04]))

    with pytest.raises(PatchError, match="source does not match"):
        apply_patch(patch, headered())


def test_an_unknown_patch_format_is_reported() -> None:
    with pytest.raises(PatchError, match="unknown patch format"):
        apply_patch(b"nonsense", headerless())


def test_an_ips_patch_that_breaks_the_image_is_reported() -> None:
    patch = ips_setting(0x01, b"XX")

    with pytest.raises(PatchError, match="no longer parses"):
        apply_patch(patch, headerless())


def test_an_ips_patch_aimed_at_the_headerless_image_is_retried_without_the_header() -> None:
    patch = ips_setting(0x11, b"ZEL")

    outcome = apply_patch(patch, headered())

    assert outcome.applied_to == "headerless image"
    assert outcome.data[HEADER_SIZE + 0x11 : HEADER_SIZE + 0x14] == b"ZEL"


def test_the_outcome_names_the_patch_format() -> None:
    outcome = apply_patch(ips_setting(0x10, b"ZEL"), headerless())

    assert isinstance(outcome, PatchOutcome)
    assert str(outcome.format) == "ips"


def test_a_ups_patch_for_the_headerless_image_is_retried_without_the_header() -> None:
    from tests.formats.test_formats import build_ups

    target = bytearray(headerless())
    target[0x11:0x14] = b"ZEL"
    patch = build_ups(headerless(), bytes(target))

    outcome = apply_patch(patch, headered())

    assert outcome.applied_to == "headerless image"
    assert outcome.format is PatchFormat.UPS
