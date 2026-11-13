from __future__ import annotations

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.foreign import ForeignImageError, foreign_format, reject_foreign


def test_an_hxc_flux_image_is_recognised() -> None:
    # Arrange
    data = b"HXCQDDRV" + bytes(504)

    # Act
    result = foreign_format(data)

    # Assert
    assert result == "an HxC Floppy Emulator flux image"


def test_a_sharp_mz_qdf_image_is_recognised() -> None:
    # Arrange
    image = b"-QD format-" + b"\xff" * 5 + bytes(100)

    # Act
    found = foreign_format(image)

    # Assert
    assert found == "a Sharp MZ Quick Disk image in QDF form"


def test_a_sharp_mz_mzq_image_is_recognised() -> None:
    # Arrange
    image = b"\x00\x16\x16\xa5\x02CRC" + bytes(100)

    # Act
    found = foreign_format(image)

    # Assert
    assert found == "a Sharp MZ Quick Disk image in MZQ form"


def test_a_famicom_image_is_not_foreign() -> None:
    # Arrange
    data = blank_image(sides=1, headered=False, formatted=True)

    # Act
    result = foreign_format(data)

    # Assert
    assert result is None


def test_an_unformatted_famicom_image_is_not_foreign() -> None:
    # Arrange
    data = blank_image(sides=1, headered=False, formatted=False)

    # Act
    result = foreign_format(data)

    # Assert
    assert result is None


def test_a_short_file_is_not_foreign() -> None:
    # Arrange
    data = b"\x00\x16"

    # Act
    result = foreign_format(data)

    # Assert
    assert result is None


def test_rejecting_a_foreign_image_names_it() -> None:
    # Arrange
    data = b"-QD format-" + b"\xff" * 5 + bytes(10)

    # Act
    with pytest.raises(ForeignImageError, match="Sharp MZ") as raised:
        reject_foreign(data)

    # Assert
    assert raised.type is ForeignImageError


def test_rejecting_a_famicom_image_does_nothing() -> None:
    # Arrange
    image = blank_image(sides=1, headered=False, formatted=True)

    # Act
    outcome = reject_foreign(image)

    # Assert
    assert outcome is None
