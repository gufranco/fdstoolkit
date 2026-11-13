from __future__ import annotations

import zlib

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.diagnostics import Severity
from fdstoolkit.edit.emulator import SaveFormat, detect_save_format, extract_save, merge_save
from fdstoolkit.patch.build import build_ips, build_ups
from fdstoolkit.patch.formats import PatchError, write_varint


def original() -> bytes:
    return blank_image(sides=1, headered=False, formatted=True, game_name="SMB")


def played() -> bytes:
    data = bytearray(original())
    data[70:78] = bytes([0x11]) * 8
    return bytes(data)


def test_an_ips_save_is_detected() -> None:
    # Arrange
    save = build_ips(original(), played())

    # Act
    result = detect_save_format(save)

    # Assert
    assert result is SaveFormat.IPS


def test_a_full_image_save_is_detected() -> None:
    # Arrange
    save = played()

    # Act
    result = detect_save_format(save)

    # Assert
    assert result is SaveFormat.IMAGE


def test_an_unrecognised_save_is_detected() -> None:
    # Arrange
    save = bytes([0x01, 0x02, 0x03])

    # Act
    result = detect_save_format(save)

    # Assert
    assert result is SaveFormat.UNKNOWN


def test_an_ips_save_merges_onto_the_original() -> None:
    # Arrange
    source = original()
    target = played()

    # Act
    save = build_ips(source, target)

    # Assert
    assert merge_save(original(), save) == played()


def test_a_full_image_save_replaces_the_original() -> None:
    # Arrange
    image = original()
    save = played()

    # Act
    result = merge_save(image, save)

    # Assert
    assert result == played()


def test_a_full_image_save_for_another_disk_is_refused() -> None:
    # Arrange
    other = blank_image(sides=2, headered=False, formatted=True)

    # Act
    with pytest.raises(PatchError, match="does not match") as raised:
        merge_save(original(), other)

    # Assert
    assert raised.type is PatchError


def test_a_save_that_is_not_a_whole_number_of_sides_is_refused() -> None:
    # Arrange
    image = original()
    save = played() + bytes(10)

    # Act
    with pytest.raises(PatchError, match="not a save") as raised:
        merge_save(image, save)

    # Assert
    assert raised.type is PatchError


def test_an_unrecognised_save_is_refused() -> None:
    # Arrange
    image = original()
    save = bytes([0x01, 0x02, 0x03])

    # Act
    with pytest.raises(PatchError, match="not a save") as raised:
        merge_save(image, save)

    # Assert
    assert raised.type is PatchError


def test_extracting_produces_a_patch_that_replays_the_save() -> None:
    # Arrange
    expected = played()

    # Act
    save = extract_save(original(), played())

    # Assert
    assert merge_save(original(), save) == expected


def test_extracting_from_an_unplayed_disk_produces_an_empty_patch() -> None:
    # Arrange
    played = original()

    # Act
    save = extract_save(original(), played)

    # Assert
    assert merge_save(original(), save) == original()


def test_extracting_can_emit_a_whole_image() -> None:
    # Arrange
    expected = played()

    # Act
    save = extract_save(original(), played(), fmt=SaveFormat.IMAGE)

    # Assert
    assert save == expected


def test_extracting_refuses_an_unknown_format() -> None:
    # Arrange
    fmt = SaveFormat.UNKNOWN

    # Act
    with pytest.raises(PatchError, match="cannot write") as raised:
        extract_save(original(), played(), fmt=fmt)

    # Assert
    assert raised.type is PatchError


def test_merging_keeps_the_disk_parseable() -> None:
    # Arrange
    merged = merge_save(original(), build_ips(original(), played()))

    # Act
    _, findings = decode(merged)

    # Assert
    assert merged == played()
    assert all(finding.severity is not Severity.ERROR for finding in findings)


def test_a_ups_save_is_detected() -> None:
    # Arrange
    save = build_ups(original(), played())

    # Act
    result = detect_save_format(save)

    # Assert
    assert result is SaveFormat.UPS


def test_a_bps_save_is_detected() -> None:
    # Arrange
    save = b"BPS1" + bytes(20)

    # Act
    result = detect_save_format(save)

    # Assert
    assert result is SaveFormat.BPS


def test_a_ups_save_merges_into_the_image() -> None:
    # Arrange
    image = original()
    save = build_ups(original(), played())

    # Act
    result = merge_save(image, save)

    # Assert
    assert result == played()


def test_a_ups_save_against_another_disk_is_refused() -> None:
    # Arrange
    other = blank_image(sides=1, headered=False, formatted=True, game_name="ZEL")

    # Act
    with pytest.raises(PatchError, match="does not match the patch") as raised:
        merge_save(other, build_ups(original(), played()))

    # Assert
    assert raised.type is PatchError


def test_a_save_can_be_written_as_ups() -> None:
    # Arrange
    expected = played()

    # Act
    save = extract_save(original(), played(), fmt=SaveFormat.UPS)

    # Assert
    assert merge_save(original(), save) == expected


def test_a_bps_save_merges_into_the_image() -> None:
    # Arrange
    expected = played()

    # Act
    patch = build_bps_copy(original(), played())

    # Assert
    assert merge_save(original(), patch) == expected


def test_a_headerless_whole_image_save_merges_into_a_headered_image() -> None:
    # Arrange
    headered = b"FDS\x1a\x01" + bytes(11) + original()

    # Act
    merged = merge_save(headered, played())

    # Assert
    assert merged[:16] == headered[:16]
    assert merged[16:] == played()


def test_a_headered_whole_image_save_merges_into_a_headerless_image() -> None:
    # Arrange
    expected = played()

    # Act
    save = b"FDS\x1a\x01" + bytes(11) + played()

    # Assert
    assert merge_save(original(), save) == expected


def test_a_bps_save_cannot_be_written() -> None:
    # Arrange
    fmt = SaveFormat.BPS

    # Act
    with pytest.raises(PatchError, match="cannot write a save as bps") as raised:
        extract_save(original(), played(), fmt=fmt)

    # Assert
    assert raised.type is PatchError


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
    # Arrange
    changed = bytearray(original())
    changed[-1] = 0x42

    # Act
    save = extract_save(original(), bytes(changed), fmt=SaveFormat.UPS)

    # Assert
    assert merge_save(original(), save) == bytes(changed)
