from __future__ import annotations

import pytest

from fdstoolkit.core.diskinfo import (
    CONTENT_PROFILE,
    DATA_PROFILE,
    DISK_INFO_FIELDS,
    RAW_PROFILE,
    DiskInfo,
    bcd_to_int,
    mask_disk_info,
)


def build_payload(**overrides: bytes) -> bytes:
    payload = bytearray(56)
    payload[0] = 0x01
    payload[1:15] = b"*NINTENDO-HVC*"
    payload[0x0F] = 0x01
    payload[0x10:0x13] = b"SMB"
    payload[0x13] = 0x20
    payload[0x14] = 0x00
    payload[0x15] = 0x00
    payload[0x16] = 0x00
    payload[0x17] = 0x00
    payload[0x19] = 0x00
    payload[0x1A:0x1F] = bytes([0xFF] * 5)
    payload[0x1F:0x22] = bytes([0x61, 0x02, 0x15])
    payload[0x22] = 0x49
    payload[0x2C:0x2F] = bytes([0x63, 0x08, 0x01])
    payload[0x31:0x33] = bytes([0x34, 0x12])
    payload[0x34] = 0x03
    payload[0x35] = 0x01
    payload[0x36] = 0xFF
    payload[0x37] = 0x02
    for name, value in overrides.items():
        field = next(f for f in DISK_INFO_FIELDS if f.name == name)
        payload[field.offset : field.offset + field.length] = value
    return bytes(payload)


def test_disk_info_parses_the_verification_string() -> None:
    # Arrange
    payload = build_payload()

    # Act
    info = DiskInfo.parse(payload)

    # Assert
    assert info.verification == b"*NINTENDO-HVC*"
    assert info.is_verified


def test_disk_info_reports_an_unverified_disk() -> None:
    # Arrange
    payload = build_payload(verification=b"*NOT-NINTENDO*")

    # Act
    info = DiskInfo.parse(payload)

    # Assert
    assert not info.is_verified


def test_disk_info_parses_identity_fields() -> None:
    # Arrange
    payload = build_payload()

    # Act
    info = DiskInfo.parse(payload)

    # Assert
    assert info.licensee == 0x01
    assert info.game_name == "SMB"
    assert info.game_type == 0x20
    assert info.game_version == 0
    assert info.side == 0
    assert info.disk_number == 0
    assert info.boot_file == 0


def test_disk_info_parses_provenance_fields() -> None:
    # Arrange
    payload = build_payload()

    # Act
    info = DiskInfo.parse(payload)

    # Assert
    assert info.manufacturing_date == (1986, 2, 15)
    assert info.rewritten_date == (1988, 8, 1)
    assert info.writer_serial == 0x1234
    assert info.rewrite_count == 3
    assert info.actual_side == 1
    assert info.disk_type == 0xFF
    assert info.disk_version == 2


def test_a_date_with_invalid_bcd_digits_is_reported_as_none() -> None:
    # Arrange
    payload = build_payload(manufacturing_date=bytes([0xAB, 0x02, 0x15]))

    # Act
    info = DiskInfo.parse(payload)

    # Assert
    assert info.manufacturing_date is None


def test_bcd_conversion_rejects_a_non_decimal_nibble() -> None:
    # Arrange
    value = 0x1A

    # Act
    result = bcd_to_int(value)

    # Assert
    assert result is None
    assert bcd_to_int(0x29) == 29


def test_disk_info_rejects_a_short_payload() -> None:
    # Arrange
    payload = bytes(10)

    # Act
    with pytest.raises(ValueError, match="56 bytes") as raised:
        DiskInfo.parse(payload)

    # Assert
    assert raised.type is ValueError


def test_raw_profile_masks_nothing() -> None:
    # Arrange
    payload = build_payload()

    # Act
    masked = mask_disk_info(payload, RAW_PROFILE)

    # Assert
    assert masked == payload


def test_content_profile_erases_provenance_but_keeps_identity() -> None:
    # Arrange
    factory = build_payload(
        manufacturing_date=bytes([0x61, 0x02, 0x15]),
        rewritten_date=bytes([0x61, 0x02, 0x15]),
        writer_serial=bytes([0x00, 0x00]),
        rewrite_count=bytes([0x00]),
    )

    # Act
    rewritten = build_payload()

    # Assert
    assert mask_disk_info(factory, CONTENT_PROFILE) == mask_disk_info(rewritten, CONTENT_PROFILE)
    assert mask_disk_info(factory, CONTENT_PROFILE)[0x10:0x13] == b"SMB"


def test_content_profile_keeps_a_different_game_distinct() -> None:
    # Arrange
    one = build_payload()

    # Act
    other = build_payload(game_name=b"ZEL")

    # Assert
    assert mask_disk_info(one, CONTENT_PROFILE) != mask_disk_info(other, CONTENT_PROFILE)


def test_content_profile_keeps_the_game_version_distinct() -> None:
    # Arrange
    one = build_payload()

    # Act
    other = build_payload(game_version=bytes([0x01]))

    # Assert
    assert mask_disk_info(one, CONTENT_PROFILE) != mask_disk_info(other, CONTENT_PROFILE)


def test_data_profile_erases_the_whole_disk_info_block() -> None:
    # Arrange
    payload = build_payload()

    # Act
    masked = mask_disk_info(payload, DATA_PROFILE)

    # Assert
    assert masked == bytes([0x01]) + bytes(55)


def test_every_profile_declares_a_version() -> None:
    # Arrange
    profiles = (RAW_PROFILE, CONTENT_PROFILE, DATA_PROFILE)

    # Act
    declared = [(profile.version >= 1, bool(profile.name)) for profile in profiles]

    # Assert
    assert declared == [(True, True)] * len(profiles)


def test_fields_cover_every_byte_of_the_block_exactly_once() -> None:
    # Arrange
    covered = [0] * 56

    # Act
    for field in DISK_INFO_FIELDS:
        for index in range(field.offset, field.offset + field.length):
            covered[index] += 1

    # Assert
    assert covered == [1] * 56


def test_masking_rejects_a_block_of_the_wrong_length() -> None:
    # Arrange
    payload = bytes(10)

    # Act
    with pytest.raises(ValueError, match="56 bytes") as raised:
        mask_disk_info(payload, RAW_PROFILE)

    # Assert
    assert raised.type is ValueError


def test_disk_info_exposes_every_scalar_field() -> None:
    # Arrange
    payload = build_payload()

    # Act
    info = DiskInfo.parse(payload)

    # Assert
    assert info.country == 0x49
    assert info.disk_version == 2
    assert info.masked(RAW_PROFILE) == info.payload
