from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import pytest
from fdspacker_kit import DEFAULT_INFO, GAME, OTHER_GAME, build, info_of, packer_file, packer_side

from fdstoolkit.build.fdspacker import FdsPackerError, FdsPackerManifest
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.files import extract_files


def test_a_manifest_with_fdspacker_side_keys_is_recognised(tmp_path: Path) -> None:
    # Arrange
    payload = {"sides": [packer_side(tmp_path, disk_side="A")]}

    # Act
    recognised = FdsPackerManifest.recognises(payload)

    # Assert
    assert recognised is True


def test_a_manifest_with_fdspacker_file_keys_is_recognised(tmp_path: Path) -> None:
    # Arrange
    payload = {"sides": [{"files": [packer_file(tmp_path, 0)]}]}

    # Act
    recognised = FdsPackerManifest.recognises(payload)

    # Assert
    assert recognised is True


def test_a_manifest_in_the_toolkit_schema_is_not_recognised() -> None:
    # Arrange
    payload = {
        "game_name": GAME,
        "sides": [{"side": 0, "files": [{"name": "MAIN", "path": "main.prg"}]}],
    }

    # Act
    recognised = FdsPackerManifest.recognises(payload)

    # Assert
    assert recognised is False


def test_a_side_left_to_defaults_carries_fdspacker_defaults(tmp_path: Path) -> None:
    # Arrange
    disk = build(tmp_path, packer_side(tmp_path))

    # Act
    info = info_of(disk)

    # Assert
    assert info == DEFAULT_INFO


EVERY_FIELD: dict[str, object] = {
    "licensee_code": "$A4",
    "game_name": OTHER_GAME,
    "game_type": "E",
    "game_version": 2,
    "disk_side": "B",
    "disk_number": 1,
    "disk_type": "FSC",
    "unknown01": "$11",
    "boot_file": 15,
    "unknown02": "$21",
    "unknown03": "$22",
    "unknown04": "$23",
    "unknown05": "$24",
    "unknown06": "$25",
    "manufacturing_date": "1986-02-21",
    "country_code": "Japan",
    "unknown07": "$31",
    "unknown08": "$32",
    "unknown09": "$33",
    "unknown10": "$34",
    "unknown11": "$35",
    "unknown12": "$36",
    "unknown13": "$37",
    "unknown14": "$38",
    "unknown15": "$39",
    "rewritten_date": "1988-12-01",
    "unknown16": "$41",
    "unknown17": "$42",
    "disk_writer_serial_number": "$1234",
    "unknown18": "$43",
    "disk_rewrite_count": 12,
    "actual_disk_side": "B",
    "disk_type_other": "BlueDisk",
    "disk_version": "$05",
}

EVERY_FIELD_INFO = (
    b"\x01*NINTENDO-HVC*\xa4"
    + OTHER_GAME.encode("ascii")
    + b"E\x02\x01\x01\x01\x11\x0f\x21\x22\x23\x24\x25"
    b"\x61\x02\x21\x49\x31\x32\x33\x34\x35\x36\x37\x38\x39"
    b"\x63\x12\x01\x41\x42\x34\x12\x43\x12\x01\xff\x05"
)


def test_every_named_field_lands_at_its_offset(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, **EVERY_FIELD)
    expected = EVERY_FIELD_INFO

    # Act
    info = info_of(build(tmp_path, side))

    # Assert
    assert info == expected


def test_numbers_accept_dollar_hex_prefixed_hex_and_decimal(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, licensee_code="0x10", game_version="$10", disk_number="10")

    # Act
    info = info_of(build(tmp_path, side))

    # Assert
    assert (info[0x0F], info[0x14], info[0x16]) == (0x10, 0x10, 10)


def test_enum_names_are_read_without_regard_to_case(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(
        tmp_path,
        disk_side="b",
        disk_type="fsc",
        disk_type_other="prototypesample",
        files=[packer_file(tmp_path, 0, file_kind="nametable")],
    )
    disk = build(tmp_path, side)

    # Act
    info = info_of(disk)

    # Assert
    assert (info[0x15], info[0x17], info[0x36]) == (1, 1, 0xFE)
    assert extract_files(disk)[0].kind is FileKind.NAMETABLE


@pytest.mark.parametrize(("name", "code"), [("Nintendo", 0x01), ("konami", 0xA4), ("CAPCOM", 0x08)])
def test_a_licensee_given_by_fdspacker_name_is_its_code(
    tmp_path: Path, name: str, code: int
) -> None:
    # Arrange
    side = packer_side(tmp_path, licensee_code=name)

    # Act
    info = info_of(build(tmp_path, side))

    # Assert
    assert info[0x0F] == code


def test_a_licensee_name_fdspacker_does_not_know_is_refused_with_a_hex_hint(
    tmp_path: Path,
) -> None:
    # Arrange
    side = packer_side(tmp_path, licensee_code="Acme Software")

    # Act
    with pytest.raises(ValueError, match=r"licensee_code 'Acme Software'.*such as \$01") as raised:
        build(tmp_path, side)

    # Assert
    assert raised.type is FdsPackerError


def test_the_licensee_table_holds_fdspacker_codes_once_each() -> None:
    # Arrange
    table = json.loads(
        resources.files("fdstoolkit.data").joinpath("licensees.json").read_text(encoding="utf-8")
    )

    # Act
    codes = list(table["licensees"])

    # Assert
    assert len(codes) == 142
    assert len(set(table["licensees"].values())) == 142
    assert table["licensees"]["0x01"] == "Nintendo"


def test_an_unknown_enum_name_is_refused_with_the_known_names(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, disk_side="C")

    # Act
    with pytest.raises(ValueError, match=r"disk_side 'C'.*A, B") as raised:
        build(tmp_path, side)

    # Assert
    assert raised.type is FdsPackerError


def test_a_byte_field_beyond_a_byte_is_refused(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, unknown07="$100")

    # Act
    with pytest.raises(ValueError, match=r"unknown07 is 256") as raised:
        build(tmp_path, side)

    # Assert
    assert raised.type is FdsPackerError


def test_a_true_or_false_number_is_refused(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, game_version=True)

    # Act
    with pytest.raises(ValueError, match=r"game_version") as raised:
        build(tmp_path, side)

    # Assert
    assert raised.type is FdsPackerError


def test_a_game_type_of_one_character_is_that_character(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, game_type="R")

    # Act
    info = info_of(build(tmp_path, side))

    # Assert
    assert info[0x13] == ord("R")


def test_a_game_type_in_hex_is_that_byte(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, game_type="$00")

    # Act
    info = info_of(build(tmp_path, side))

    # Assert
    assert info[0x13] == 0
