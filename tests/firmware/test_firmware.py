from __future__ import annotations

import zlib

import pytest

from fdstk.identify import firmware
from fdstk.identify.firmware import (
    BIOS_SIZE,
    Revision,
    extract_bios,
    identify_bios,
)


def fake_bios(fill: int) -> bytes:
    return bytes([fill]) * BIOS_SIZE


@pytest.fixture
def known(monkeypatch: pytest.MonkeyPatch) -> bytes:
    data = fake_bios(0x5A)
    crc = f"{zlib.crc32(data):08x}"
    patched = {
        crc: Revision(
            name="Rev 01A",
            crc32=crc,
            sha1="0" * 40,
            mame_name="rp2c33a-01a.bin",
        )
    }
    monkeypatch.setattr(firmware, "KNOWN_REVISIONS", patched)
    return data


def test_the_three_revisions_carry_mames_hashes() -> None:
    names = {revision.name: revision.crc32 for revision in firmware.KNOWN_REVISIONS.values()}

    assert names == {"Rev 01": "1c7ae5d5", "Rev 01A": "5e607dcf", "Rev 02": "4df24a6c"}


def test_an_exact_eight_kilobyte_bios_is_identified(known: bytes) -> None:
    report = identify_bios(known)

    assert report.revision is not None
    assert report.revision.name == "Rev 01A"
    assert report.offset == 0
    assert report.exact_size


def test_a_bios_inside_a_forty_kilobyte_dump_is_found(known: bytes) -> None:
    wrapped = bytes(0x6000) + known + bytes(0x2000)

    report = identify_bios(wrapped)

    assert report.revision is not None
    assert report.offset == 0x6000
    assert not report.exact_size


def test_a_bios_behind_an_ines_header_is_found(known: bytes) -> None:
    wrapped = b"NES\x1a" + bytes(12) + bytes(0x6000) + known + bytes(0x2000)

    report = identify_bios(wrapped)

    assert report.offset == 16 + 0x6000


@pytest.mark.usefixtures("known")
def test_an_unknown_eight_kilobyte_file_is_reported_as_unknown() -> None:
    report = identify_bios(fake_bios(0x11))

    assert report.revision is None
    assert report.exact_size
    assert report.crc32 == f"{zlib.crc32(fake_bios(0x11)):08x}"


@pytest.mark.usefixtures("known")
def test_a_file_too_small_to_hold_a_bios_is_reported() -> None:
    report = identify_bios(bytes(100))

    assert report.revision is None
    assert report.offset is None


def test_extracting_returns_the_eight_kilobytes(known: bytes) -> None:
    wrapped = bytes(0x6000) + known + bytes(0x2000)

    assert extract_bios(wrapped) == known


@pytest.mark.usefixtures("known")
def test_extracting_from_a_file_with_no_known_bios_is_refused() -> None:
    with pytest.raises(ValueError, match="no known BIOS"):
        extract_bios(bytes(0xA000))


def test_nestopia_warns_on_the_first_revision() -> None:
    first = next(r for r in firmware.KNOWN_REVISIONS.values() if r.name == "Rev 01")

    notes = firmware.emulator_notes(first, exact_size=True)

    assert notes["nestopia"] == "loads it with a warning, it only knows Rev 01A and Rev 02"


def test_every_emulator_accepts_a_known_eight_kilobyte_bios() -> None:
    second = next(r for r in firmware.KNOWN_REVISIONS.values() if r.name == "Rev 01A")

    notes = firmware.emulator_notes(second, exact_size=True)

    assert notes["mesen2"] == "accepts it"
    assert notes["fceux"] == "accepts it"
    assert notes["nestopia"] == "accepts it"


def test_every_emulator_rejects_a_bios_of_the_wrong_size() -> None:
    notes = firmware.emulator_notes(None, exact_size=False)

    assert notes["fceux"].startswith("rejects it")
    assert notes["mesen2"].startswith("rejects it")
    assert notes["nestopia"].startswith("rejects it")


def test_an_unknown_bios_of_the_right_size_is_loaded_with_a_warning_by_nestopia() -> None:
    notes = firmware.emulator_notes(None, exact_size=True)

    assert notes["nestopia"].startswith("loads it with a warning")
    assert notes["fceux"] == "accepts it"


def test_a_re_release_variant_is_identified_with_its_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = fake_bios(0x33)
    crc = f"{zlib.crc32(data):08x}"
    variant = Revision(
        name="Rev 1, Animal Crossing",
        crc32=crc,
        sha1="0" * 40,
        mame_name=None,
        source=firmware.VARIANT_SOURCE,
    )
    monkeypatch.setattr(firmware, "KNOWN_VARIANTS", {crc: variant})

    report = identify_bios(data)

    assert report.revision is variant
    assert variant.mame_name is None


def test_every_variant_is_distinct_from_the_mame_revisions() -> None:
    assert not set(firmware.KNOWN_VARIANTS) & set(firmware.KNOWN_REVISIONS)
