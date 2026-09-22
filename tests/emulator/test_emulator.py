from __future__ import annotations

import zlib

import pytest

from fdstk.build.blank import blank_image
from fdstk.codecs.fds import decode
from fdstk.core.diagnostics import Severity
from fdstk.edit.emulator import SaveFormat, detect_save_format, extract_save, merge_save
from fdstk.patch.build import build_ips, build_ups
from fdstk.patch.formats import PatchError, write_varint


def original() -> bytes:
    return blank_image(sides=1, headered=False, formatted=True, game_name="SMB")


def played() -> bytes:
    data = bytearray(original())
    data[70:78] = bytes([0x11]) * 8
    return bytes(data)


def test_an_ips_save_is_detected() -> None:
    assert detect_save_format(build_ips(original(), played())) is SaveFormat.IPS


def test_a_full_image_save_is_detected() -> None:
    assert detect_save_format(played()) is SaveFormat.IMAGE


def test_an_unrecognised_save_is_detected() -> None:
    assert detect_save_format(bytes([0x01, 0x02, 0x03])) is SaveFormat.UNKNOWN


def test_an_ips_save_merges_onto_the_original() -> None:
    save = build_ips(original(), played())

    assert merge_save(original(), save) == played()


def test_a_full_image_save_replaces_the_original() -> None:
    assert merge_save(original(), played()) == played()


def test_a_full_image_save_for_another_disk_is_refused() -> None:
    other = blank_image(sides=2, headered=False, formatted=True)

    with pytest.raises(PatchError, match="does not match"):
        merge_save(original(), other)


def test_a_save_that_is_not_a_whole_number_of_sides_is_refused() -> None:
    with pytest.raises(PatchError, match="not a save"):
        merge_save(original(), played() + bytes(10))


def test_an_unrecognised_save_is_refused() -> None:
    with pytest.raises(PatchError, match="not a save"):
        merge_save(original(), bytes([0x01, 0x02, 0x03]))


def test_extracting_produces_a_patch_that_replays_the_save() -> None:
    save = extract_save(original(), played())

    assert merge_save(original(), save) == played()


def test_extracting_from_an_unplayed_disk_produces_an_empty_patch() -> None:
    save = extract_save(original(), original())

    assert merge_save(original(), save) == original()


def test_extracting_can_emit_a_whole_image() -> None:
    save = extract_save(original(), played(), fmt=SaveFormat.IMAGE)

    assert save == played()


def test_extracting_refuses_an_unknown_format() -> None:
    with pytest.raises(PatchError, match="cannot write"):
        extract_save(original(), played(), fmt=SaveFormat.UNKNOWN)


def test_merging_keeps_the_disk_parseable() -> None:
    merged = merge_save(original(), build_ips(original(), played()))
    _, findings = decode(merged)

    assert merged == played()
    assert all(finding.severity is not Severity.ERROR for finding in findings)


def test_a_ups_save_is_detected() -> None:
    assert detect_save_format(build_ups(original(), played())) is SaveFormat.UPS


def test_a_bps_save_is_detected() -> None:
    assert detect_save_format(b"BPS1" + bytes(20)) is SaveFormat.BPS


def test_a_ups_save_merges_into_the_image() -> None:
    assert merge_save(original(), build_ups(original(), played())) == played()


def test_a_ups_save_against_another_disk_is_refused() -> None:
    other = blank_image(sides=1, headered=False, formatted=True, game_name="ZEL")

    with pytest.raises(PatchError, match="does not match the patch"):
        merge_save(other, build_ups(original(), played()))


def test_a_save_can_be_written_as_ups() -> None:
    save = extract_save(original(), played(), fmt=SaveFormat.UPS)

    assert merge_save(original(), save) == played()


def test_a_bps_save_merges_into_the_image() -> None:
    patch = build_bps_copy(original(), played())

    assert merge_save(original(), patch) == played()


def test_a_headerless_whole_image_save_merges_into_a_headered_image() -> None:
    headered = b"FDS\x1a\x01" + bytes(11) + original()

    merged = merge_save(headered, played())

    assert merged[:16] == headered[:16]
    assert merged[16:] == played()


def test_a_headered_whole_image_save_merges_into_a_headerless_image() -> None:
    save = b"FDS\x1a\x01" + bytes(11) + played()

    assert merge_save(original(), save) == played()


def test_a_bps_save_cannot_be_written() -> None:
    with pytest.raises(PatchError, match="cannot write a save as bps"):
        extract_save(original(), played(), fmt=SaveFormat.BPS)


def build_bps_copy(source: bytes, target: bytes) -> bytes:
    body = bytearray(b"BPS1")
    body += write_varint(len(source))
    body += write_varint(len(target))
    body += write_varint(0)
    body += write_varint(((len(target) - 1) << 2) | 1)
    body += target
    body += zlib.crc32(source).to_bytes(4, "little")
    body += zlib.crc32(target).to_bytes(4, "little")
    body += zlib.crc32(bytes(body)).to_bytes(4, "little")
    return bytes(body)


def test_a_ups_save_changing_the_last_byte_round_trips() -> None:
    changed = bytearray(original())
    changed[-1] = 0x42

    save = extract_save(original(), bytes(changed), fmt=SaveFormat.UPS)

    assert merge_save(original(), save) == bytes(changed)
