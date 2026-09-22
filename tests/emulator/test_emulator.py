from __future__ import annotations

import pytest

from fdstk.build.blank import blank_image
from fdstk.codecs.fds import decode
from fdstk.core.diagnostics import Severity
from fdstk.edit.emulator import SaveFormat, detect_save_format, extract_save, merge_save
from fdstk.patch.build import build_ips
from fdstk.patch.formats import PatchError


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
