from __future__ import annotations

import pytest

from fdstoolkit.core.showa import ShowaDateError, encode_date, parse_date


def test_a_date_inside_the_showa_count_is_parsed() -> None:
    # Arrange
    written = "1986-02-21"

    # Act
    found = parse_date(written, field="manufacturing_date")

    # Assert
    assert found == (1986, 2, 21)


def test_a_date_is_encoded_as_bcd_years_since_1925() -> None:
    # Arrange
    day = (1986, 2, 21)

    # Act
    encoded = encode_date(*day)

    # Assert
    assert encoded == bytes([0x61, 0x02, 0x21])


@pytest.mark.parametrize("written", ["1990-13-01", "1990-02-30"])
def test_a_day_that_is_not_on_the_calendar_is_refused(written: str) -> None:
    # Arrange
    field = "manufacturing_date"

    # Act
    with pytest.raises(ShowaDateError, match="is not a day on the calendar") as raised:
        parse_date(written, field=field)

    # Assert
    assert raised.type is ShowaDateError


@pytest.mark.parametrize("written", ["1924-12-31", "2025-01-01", "2030-01-01"])
def test_a_year_the_two_bcd_digits_cannot_hold_is_refused(written: str) -> None:
    # Arrange
    field = "rewritten_date"

    # Act
    with pytest.raises(ShowaDateError, match="outside 1925 to 2024") as raised:
        parse_date(written, field=field)

    # Assert
    assert raised.type is ShowaDateError


def test_the_last_year_two_bcd_digits_hold_is_accepted() -> None:
    # Arrange
    written = "2024-12-31"

    # Act
    found = parse_date(written, field="manufacturing_date")

    # Assert
    assert encode_date(*found) == bytes([0x99, 0x12, 0x31])
