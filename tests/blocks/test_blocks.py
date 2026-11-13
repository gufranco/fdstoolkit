from __future__ import annotations

import pytest

from fdstoolkit.core.blocks import (
    Block,
    BlockKind,
    CrcStatus,
    FileHeader,
    FileKind,
    expected_kind,
)
from fdstoolkit.core.crc import block_crc


def disk_info_payload() -> bytes:
    return bytes([BlockKind.DISK_INFO]) + b"*NINTENDO-HVC*" + bytes(41)


def file_header_payload(size: int = 4) -> bytes:
    return (
        bytes([BlockKind.FILE_HEADER, 0x00, 0x00])
        + b"HELLO   "
        + (0x6000).to_bytes(2, "little")
        + size.to_bytes(2, "little")
        + bytes([FileKind.PROGRAM])
    )


def test_a_block_knows_its_own_length() -> None:
    # Arrange
    payload = bytes([0x02, 0x03])

    # Act
    block = Block(kind=BlockKind.FILE_AMOUNT, payload=payload)

    # Assert
    assert block.size == 2


def test_a_block_rejects_a_payload_whose_first_byte_is_not_its_kind() -> None:
    # Arrange
    payload = bytes([0x03, 0x00])

    # Act
    with pytest.raises(ValueError, match="kind byte") as raised:
        Block(kind=BlockKind.FILE_AMOUNT, payload=payload)

    # Assert
    assert raised.type is ValueError


def test_a_fixed_size_block_rejects_the_wrong_length() -> None:
    # Arrange
    payload = bytes([0x01, 0x02])

    # Act
    with pytest.raises(ValueError, match="56 bytes") as raised:
        Block(kind=BlockKind.DISK_INFO, payload=payload)

    # Assert
    assert raised.type is ValueError


def test_a_data_block_accepts_any_length_above_the_kind_byte() -> None:
    # Arrange
    payload = bytes([0x04, 0xAA, 0xBB])

    # Act
    block = Block(kind=BlockKind.FILE_DATA, payload=payload)

    # Assert
    assert block.size == 3


def test_an_empty_payload_is_rejected() -> None:
    # Arrange
    payload = b""

    # Act
    with pytest.raises(ValueError, match="empty") as raised:
        Block(kind=BlockKind.FILE_DATA, payload=payload)

    # Assert
    assert raised.type is ValueError


def test_crc_is_absent_when_the_format_carries_none() -> None:
    # Arrange
    payload = bytes([0x02, 0x01])

    # Act
    block = Block(kind=BlockKind.FILE_AMOUNT, payload=payload)

    # Assert
    assert block.crc_status is CrcStatus.ABSENT


def test_crc_is_valid_when_the_stored_value_matches() -> None:
    # Arrange
    payload = bytes([0x02, 0x01])

    # Act
    block = Block(kind=BlockKind.FILE_AMOUNT, payload=payload, stored_crc=block_crc(payload))

    # Assert
    assert block.crc_status is CrcStatus.VALID


def test_crc_is_null_when_the_stored_value_is_zero() -> None:
    # Arrange
    payload = bytes([0x02, 0x01])
    stored_crc = 0

    # Act
    block = Block(kind=BlockKind.FILE_AMOUNT, payload=payload, stored_crc=stored_crc)

    # Assert
    assert block.crc_status is CrcStatus.NULL


def test_crc_is_a_mismatch_when_the_stored_value_is_wrong() -> None:
    # Arrange
    payload = bytes([0x02, 0x01])
    stored_crc = 0x1234

    # Act
    block = Block(kind=BlockKind.FILE_AMOUNT, payload=payload, stored_crc=stored_crc)

    # Assert
    assert block.crc_status is CrcStatus.MISMATCH


def test_with_computed_crc_returns_a_block_that_verifies() -> None:
    # Arrange
    block = Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([0x02, 0x01]))

    # Act
    stamped = block.with_computed_crc()

    # Assert
    assert stamped.crc_status is CrcStatus.VALID
    assert block.crc_status is CrcStatus.ABSENT


def test_with_null_crc_returns_a_block_carrying_zero() -> None:
    # Arrange
    payload = bytes([0x02, 0x01])

    # Act
    block = Block(kind=BlockKind.FILE_AMOUNT, payload=payload)

    # Assert
    assert block.with_null_crc().stored_crc == 0


def test_without_crc_drops_the_stored_value() -> None:
    # Arrange
    payload = bytes([0x02, 0x01])
    stored_crc = 0x1234

    # Act
    block = Block(kind=BlockKind.FILE_AMOUNT, payload=payload, stored_crc=stored_crc)

    # Assert
    assert block.without_crc().stored_crc is None


def test_a_file_header_parses_its_fields() -> None:
    # Arrange
    payload = file_header_payload(size=0x1234)

    # Act
    header = FileHeader.parse(payload)

    # Assert
    assert header.number == 0
    assert header.file_id == 0
    assert header.name == "HELLO"
    assert header.address == 0x6000
    assert header.size == 0x1234
    assert header.kind is FileKind.PROGRAM


def test_a_file_header_keeps_an_unknown_kind_value() -> None:
    # Arrange
    payload = bytearray(file_header_payload())
    payload[0x0F] = 0x09

    # Act
    header = FileHeader.parse(bytes(payload))

    # Assert
    assert header.kind is FileKind.UNKNOWN
    assert header.raw_kind == 0x09


def test_a_file_header_name_keeps_bytes_that_are_not_ascii() -> None:
    # Arrange
    payload = bytearray(file_header_payload())
    payload[3:11] = bytes([0xFF, 0x41, 0x20, 0x20, 0x20, 0x20, 0x20, 0x20])

    # Act
    header = FileHeader.parse(bytes(payload))

    # Assert
    assert header.raw_name == bytes([0xFF, 0x41, 0x20, 0x20, 0x20, 0x20, 0x20, 0x20])


def test_a_file_header_rejects_a_short_payload() -> None:
    # Arrange
    payload = bytes([0x03, 0x00])

    # Act
    with pytest.raises(ValueError, match="16 bytes") as raised:
        FileHeader.parse(payload)

    # Assert
    assert raised.type is ValueError


def test_disk_info_block_accepts_the_canonical_payload() -> None:
    # Arrange
    payload = disk_info_payload()

    # Act
    block = Block(kind=BlockKind.DISK_INFO, payload=payload)

    # Assert
    assert block.size == 56


def test_the_expected_kind_follows_the_order_a_side_is_written_in() -> None:
    # Arrange
    expected = [
        BlockKind.DISK_INFO,
        BlockKind.FILE_AMOUNT,
        BlockKind.FILE_HEADER,
        BlockKind.FILE_DATA,
        BlockKind.FILE_HEADER,
        BlockKind.FILE_DATA,
    ]

    # Act
    kinds = [expected_kind(index) for index in range(6)]

    # Assert
    assert kinds == expected
