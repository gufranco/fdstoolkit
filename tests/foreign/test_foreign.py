from __future__ import annotations

import pytest

from fdstk.build.blank import blank_image
from fdstk.codecs.foreign import ForeignImageError, foreign_format, reject_foreign


def test_an_hxc_flux_image_is_recognised() -> None:
    assert foreign_format(b"HXCQDDRV" + bytes(504)) == "an HxC Floppy Emulator flux image"


def test_a_sharp_mz_qdf_image_is_recognised() -> None:
    header = b"-QD format-" + b"\xff" * 5

    assert foreign_format(header + bytes(100)) == "a Sharp MZ Quick Disk image in QDF form"


def test_a_sharp_mz_mzq_image_is_recognised() -> None:
    header = b"\x00\x16\x16\xa5\x02CRC"

    assert foreign_format(header + bytes(100)) == "a Sharp MZ Quick Disk image in MZQ form"


def test_a_famicom_image_is_not_foreign() -> None:
    assert foreign_format(blank_image(sides=1, headered=False, formatted=True)) is None


def test_an_unformatted_famicom_image_is_not_foreign() -> None:
    assert foreign_format(blank_image(sides=1, headered=False, formatted=False)) is None


def test_a_short_file_is_not_foreign() -> None:
    assert foreign_format(b"\x00\x16") is None


def test_rejecting_a_foreign_image_names_it() -> None:
    with pytest.raises(ForeignImageError, match="Sharp MZ"):
        reject_foreign(b"-QD format-" + b"\xff" * 5 + bytes(10))


def test_rejecting_a_famicom_image_does_nothing() -> None:
    reject_foreign(blank_image(sides=1, headered=False, formatted=True))
