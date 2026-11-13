from __future__ import annotations

import pytest

from fdstoolkit.codecs.qdc import QdcError, is_qdc, qdc_counts

START = bytes([0x00, 0x00, 0x00, 0x00])
END = bytes([0x00, 0x00, 0x00, 0xFF])


def test_a_count_under_256_is_one_byte() -> None:
    # Arrange
    data = START + bytes([0x1B, 0x28]) + END

    # Act
    counts = qdc_counts(data)

    # Assert
    assert counts == (0x1B, 0x28)


def test_a_count_of_256_or_more_follows_the_16_bit_header() -> None:
    # Arrange
    data = START + bytes([0x00, 0x01, 0xCD, 0xAB]) + END

    # Act
    counts = qdc_counts(data)

    # Assert
    assert counts == (0xABCD,)


def test_an_overflow_adds_65536_per_count_to_the_remainder_before_it() -> None:
    # Arrange
    data = START + bytes([0x5A, 0x00, 0x02, 0x01, 0x00]) + END

    # Act
    counts = qdc_counts(data)

    # Assert
    assert counts == (65536 + 90,)


def test_a_wide_remainder_and_many_overflows_combine() -> None:
    # Arrange
    body = bytes([0x00, 0x01, 0x39, 0x30, 0x00, 0x02, 0x2C, 0x01])

    # Act
    counts = qdc_counts(START + body + END)

    # Assert
    assert counts == (65536 * 300 + 12345,)


def test_counts_outside_the_data_markers_are_left_out() -> None:
    # Arrange
    data = bytes([0x10]) + START + bytes([0x20]) + END + bytes([0x30])

    # Act
    counts = qdc_counts(data)

    # Assert
    assert counts == (0x20,)


def test_a_file_without_an_end_marker_keeps_every_count_after_the_start() -> None:
    # Arrange
    data = START + bytes([0x20, 0x21])

    # Act
    counts = qdc_counts(data)

    # Assert
    assert counts == (0x20, 0x21)


def test_a_file_cut_inside_an_escape_is_refused() -> None:
    # Arrange
    data = START + bytes([0x00, 0x01, 0xCD])

    # Act
    with pytest.raises(QdcError, match="ends inside") as raised:
        qdc_counts(data)

    # Assert
    assert raised.type is QdcError


def test_an_unknown_escape_is_refused() -> None:
    # Arrange
    data = START + bytes([0x00, 0x07, 0x00, 0x00])

    # Act
    with pytest.raises(QdcError, match="unknown escape 0x07") as raised:
        qdc_counts(data)

    # Assert
    assert raised.type is QdcError


def test_a_qdc_file_is_recognised_by_its_start_marker() -> None:
    # Arrange
    data = START + bytes([0x20])

    # Act
    result = is_qdc(data)

    # Assert
    assert result
    assert not is_qdc(bytes([0x3E, 0x3E, 0x5D]))


def test_an_overflow_with_no_remainder_before_it_is_a_whole_count() -> None:
    # Arrange
    data = START + bytes([0x00, 0x02, 0x02, 0x00]) + END

    # Act
    counts = qdc_counts(data)

    # Assert
    assert counts == (2 * 65536,)


def test_a_reserved_special_code_is_skipped() -> None:
    # Arrange
    data = START + bytes([0x20, 0x00, 0x00, 0x00, 0x7F, 0x21]) + END

    # Act
    counts = qdc_counts(data)

    # Assert
    assert counts == (0x20, 0x21)
