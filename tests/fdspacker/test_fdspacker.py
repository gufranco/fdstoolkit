from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

from fdstoolkit.build.fdspacker import FdsPackerManifest
from fdstoolkit.build.manifest import build_manifest_file
from fdstoolkit.codecs.fds import SIDE_SIZE, decode
from fdstoolkit.core.blocks import FileHeader, FileKind
from fdstoolkit.core.disk import Disk
from fdstoolkit.edit.files import extract_files

DEFAULT_INFO = (
    b"\x01*NINTENDO-HVC*\x00SMB\x20\x00\x00\x00\x00\x00\x00"
    + b"\xff" * 5
    + b"\x00\x00\x00\x00\x61\x00\x00\x02"
    + b"\x00" * 5
    + b"\x00\x00\x00\x00\x80\x00\x00\x00\x00\x00\x00\x00"
)


def payload_of(tmp_path: Path, name: str, size: int) -> str:
    data = hashlib.shake_256(name.encode()).digest(size)
    (tmp_path / name).write_bytes(data)
    return name


def packer_file(tmp_path: Path, number: int, **fields: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "file_number": number,
        "file_indicate_code": number,
        "file_name": f"FILE{number}",
        "file_address": "$6000",
        "file_kind": "Program",
        "data": payload_of(tmp_path, f"file{number}.bin", 16 + number),
    }
    return {**entry, **fields}


def packer_side(tmp_path: Path, **fields: Any) -> dict[str, Any]:
    side: dict[str, Any] = {
        "game_name": "SMB",
        "file_amount": 1,
        "files": [packer_file(tmp_path, 0)],
    }
    return {**side, **fields}


def build(tmp_path: Path, *sides: dict[str, Any]) -> Disk:
    manifest = FdsPackerManifest.parse({"sides": list(sides)}, root=tmp_path)
    disk, _ = decode(manifest.build())
    return disk


def info_of(disk: Disk, side: int = 0) -> bytes:
    return disk.sides[side].blocks[0].payload


def test_a_manifest_with_fdspacker_side_keys_is_recognised(tmp_path: Path) -> None:
    payload = {"sides": [packer_side(tmp_path, disk_side="A")]}

    recognised = FdsPackerManifest.recognises(payload)

    assert recognised is True


def test_a_manifest_with_fdspacker_file_keys_is_recognised(tmp_path: Path) -> None:
    payload = {"sides": [{"files": [packer_file(tmp_path, 0)]}]}

    recognised = FdsPackerManifest.recognises(payload)

    assert recognised is True


def test_a_manifest_in_the_toolkit_schema_is_not_recognised() -> None:
    payload = {
        "game_name": "SMB",
        "sides": [{"side": 0, "files": [{"name": "MAIN", "path": "main.prg"}]}],
    }

    recognised = FdsPackerManifest.recognises(payload)

    assert recognised is False


def test_a_side_left_to_defaults_carries_fdspacker_defaults(tmp_path: Path) -> None:
    disk = build(tmp_path, packer_side(tmp_path))

    info = info_of(disk)

    assert info == DEFAULT_INFO


def test_every_named_field_lands_at_its_offset(tmp_path: Path) -> None:
    side = packer_side(
        tmp_path,
        licensee_code="$A4",
        game_name="ZEL",
        game_type="E",
        game_version=2,
        disk_side="B",
        disk_number=1,
        disk_type="FSC",
        unknown01="$11",
        boot_file=15,
        unknown02="$21",
        unknown03="$22",
        unknown04="$23",
        unknown05="$24",
        unknown06="$25",
        manufacturing_date="1986-02-21",
        country_code="Japan",
        unknown07="$31",
        unknown08="$32",
        unknown09="$33",
        unknown10="$34",
        unknown11="$35",
        unknown12="$36",
        unknown13="$37",
        unknown14="$38",
        unknown15="$39",
        rewritten_date="1988-12-01",
        unknown16="$41",
        unknown17="$42",
        disk_writer_serial_number="$1234",
        unknown18="$43",
        disk_rewrite_count=12,
        actual_disk_side="B",
        disk_type_other="BlueDisk",
        disk_version="$05",
    )
    expected = (
        b"\x01*NINTENDO-HVC*\xa4ZELE\x02\x01\x01\x01\x11\x0f\x21\x22\x23\x24\x25"
        b"\x61\x02\x21\x49\x31\x32\x33\x34\x35\x36\x37\x38\x39"
        b"\x63\x12\x01\x41\x42\x34\x12\x43\x12\x01\xff\x05"
    )

    info = info_of(build(tmp_path, side))

    assert info == expected


def test_numbers_accept_dollar_hex_prefixed_hex_and_decimal(tmp_path: Path) -> None:
    side = packer_side(tmp_path, licensee_code="0x10", game_version="$10", disk_number="10")

    info = info_of(build(tmp_path, side))

    assert (info[0x0F], info[0x14], info[0x16]) == (0x10, 0x10, 10)


def test_enum_names_are_read_without_regard_to_case(tmp_path: Path) -> None:
    side = packer_side(
        tmp_path,
        disk_side="b",
        disk_type="fsc",
        disk_type_other="prototypesample",
        files=[packer_file(tmp_path, 0, file_kind="nametable")],
    )

    disk = build(tmp_path, side)

    info = info_of(disk)
    assert (info[0x15], info[0x17], info[0x36]) == (1, 1, 0xFE)
    assert extract_files(disk)[0].kind is FileKind.NAMETABLE


@pytest.mark.parametrize(("name", "code"), [("Nintendo", 0x01), ("konami", 0xA4), ("CAPCOM", 0x08)])
def test_a_licensee_given_by_fdspacker_name_is_its_code(
    tmp_path: Path, name: str, code: int
) -> None:
    side = packer_side(tmp_path, licensee_code=name)

    info = info_of(build(tmp_path, side))

    assert info[0x0F] == code


def test_a_licensee_name_fdspacker_does_not_know_is_refused_with_a_hex_hint(
    tmp_path: Path,
) -> None:
    side = packer_side(tmp_path, licensee_code="Acme Software")

    with pytest.raises(ValueError, match=r"licensee_code 'Acme Software'.*such as \$01"):
        build(tmp_path, side)


def test_the_licensee_table_holds_fdspacker_codes_once_each() -> None:
    table = json.loads(
        resources.files("fdstoolkit.data").joinpath("licensees.json").read_text(encoding="utf-8")
    )

    codes = list(table["licensees"])

    assert len(codes) == 142
    assert len(set(table["licensees"].values())) == 142
    assert table["licensees"]["0x01"] == "Nintendo"


def test_an_unknown_enum_name_is_refused_with_the_known_names(tmp_path: Path) -> None:
    side = packer_side(tmp_path, disk_side="C")

    with pytest.raises(ValueError, match=r"disk_side 'C'.*A, B"):
        build(tmp_path, side)


def test_a_byte_field_beyond_a_byte_is_refused(tmp_path: Path) -> None:
    side = packer_side(tmp_path, unknown07="$100")

    with pytest.raises(ValueError, match=r"unknown07 is 256"):
        build(tmp_path, side)


def test_a_true_or_false_number_is_refused(tmp_path: Path) -> None:
    side = packer_side(tmp_path, game_version=True)

    with pytest.raises(ValueError, match=r"game_version"):
        build(tmp_path, side)


def test_a_game_type_of_one_character_is_that_character(tmp_path: Path) -> None:
    side = packer_side(tmp_path, game_type="R")

    info = info_of(build(tmp_path, side))

    assert info[0x13] == ord("R")


def test_a_game_type_in_hex_is_that_byte(tmp_path: Path) -> None:
    side = packer_side(tmp_path, game_type="$00")

    info = info_of(build(tmp_path, side))

    assert info[0x13] == 0


def test_dates_are_written_as_showa_years_in_bcd(tmp_path: Path) -> None:
    side = packer_side(tmp_path, manufacturing_date="2022-09-21T00:00:00")

    info = info_of(build(tmp_path, side))

    assert info[0x1F:0x22] == bytes([0x97, 0x09, 0x21])


def test_a_date_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    side = packer_side(tmp_path, rewritten_date="1987-02-30")

    with pytest.raises(ValueError, match=r"rewritten_date 1987-02-30"):
        build(tmp_path, side)


def test_a_date_before_showa_is_refused(tmp_path: Path) -> None:
    side = packer_side(tmp_path, manufacturing_date="1920-01-01")

    with pytest.raises(ValueError, match=r"manufacturing_date 1920-01-01"):
        build(tmp_path, side)


def test_a_date_in_another_shape_is_refused(tmp_path: Path) -> None:
    side = packer_side(tmp_path, manufacturing_date="21/09/2022")

    with pytest.raises(ValueError, match=r"YYYY-MM-DD"):
        build(tmp_path, side)


def test_a_null_game_name_leaves_the_name_empty(tmp_path: Path) -> None:
    side = packer_side(tmp_path, game_name=None)

    info = info_of(build(tmp_path, side))

    assert info[0x10:0x13] == bytes(3)


def test_a_short_game_name_is_padded_with_zeros(tmp_path: Path) -> None:
    side = packer_side(tmp_path, game_name="AB")

    info = info_of(build(tmp_path, side))

    assert info[0x10:0x13] == b"AB\x00"


def test_a_side_without_a_game_name_is_refused(tmp_path: Path) -> None:
    side: dict[str, object] = {"file_amount": 0, "disk_side": "A", "files": []}

    with pytest.raises(ValueError, match=r"side 1 has no game_name"):
        build(tmp_path, side)


def test_a_game_name_longer_than_three_is_refused(tmp_path: Path) -> None:
    side = packer_side(tmp_path, game_name="GAMENAME")

    with pytest.raises(ValueError, match=r"game_name 'GAMENAME' is longer than 3"):
        build(tmp_path, side)


def test_file_amount_is_written_as_given(tmp_path: Path) -> None:
    files = [packer_file(tmp_path, number) for number in range(3)]
    side = packer_side(tmp_path, file_amount=2, files=files)

    disk = build(tmp_path, side)

    listed = extract_files(disk)
    assert disk.sides[0].declared_file_count == 2
    assert [entry.hidden for entry in listed] == [False, False, True]


def test_a_side_without_file_amount_declares_no_files(tmp_path: Path) -> None:
    side = packer_side(tmp_path)
    del side["file_amount"]

    disk = build(tmp_path, side)

    assert disk.sides[0].declared_file_count == 0


def test_a_file_header_carries_the_listed_fields(tmp_path: Path) -> None:
    entry = packer_file(
        tmp_path,
        4,
        file_indicate_code=9,
        file_name="KYODAKU",
        file_address="$2800",
        file_kind="Character",
    )
    disk = build(tmp_path, packer_side(tmp_path, files=[entry]))

    header = FileHeader.parse(disk.sides[0].blocks[2].payload)

    assert (header.number, header.file_id) == (4, 9)
    assert header.raw_name == b"KYODAKU\x00"
    assert (header.address, header.size, header.kind) == (0x2800, 20, FileKind.CHARACTER)


def test_a_file_without_a_name_is_named_filename(tmp_path: Path) -> None:
    entry = packer_file(tmp_path, 0)
    del entry["file_name"]
    disk = build(tmp_path, packer_side(tmp_path, files=[entry]))

    header = FileHeader.parse(disk.sides[0].blocks[2].payload)

    assert header.raw_name == b"FILENAME"


def test_a_file_name_longer_than_eight_is_refused(tmp_path: Path) -> None:
    entry = packer_file(tmp_path, 0, file_name="TOOLONGNAME")

    with pytest.raises(ValueError, match=r"file_name 'TOOLONGNAME' is longer than 8"):
        build(tmp_path, packer_side(tmp_path, files=[entry]))


def test_a_null_file_name_is_refused(tmp_path: Path) -> None:
    entry = packer_file(tmp_path, 0, file_name=None)

    with pytest.raises(ValueError, match=r"file_name"):
        build(tmp_path, packer_side(tmp_path, files=[entry]))


def test_a_file_without_data_is_refused(tmp_path: Path) -> None:
    entry = packer_file(tmp_path, 0)
    del entry["data"]

    with pytest.raises(ValueError, match=r"side 1 file 1 has no data"):
        build(tmp_path, packer_side(tmp_path, files=[entry]))


def test_a_file_whose_data_is_missing_on_disk_is_refused(tmp_path: Path) -> None:
    entry = packer_file(tmp_path, 0, data="absent.bin")

    with pytest.raises(ValueError, match=r"file not found: .*absent\.bin"):
        build(tmp_path, packer_side(tmp_path, files=[entry]))


def test_a_manifest_mixing_both_schemas_is_refused(tmp_path: Path) -> None:
    side = packer_side(tmp_path, side=0)

    with pytest.raises(ValueError, match=r"mixes .*side"):
        build(tmp_path, side)


def test_a_manifest_without_sides_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"at least one side"):
        FdsPackerManifest.parse({"sides": []}, root=tmp_path)


def test_a_side_that_overflows_the_disk_is_refused(tmp_path: Path) -> None:
    entry = packer_file(tmp_path, 0, data=payload_of(tmp_path, "big.bin", SIDE_SIZE))

    with pytest.raises(ValueError, match=r"does not fit"):
        build(tmp_path, packer_side(tmp_path, files=[entry]))


def test_every_listed_side_is_built(tmp_path: Path) -> None:
    first = packer_side(tmp_path, disk_side="A")
    second = packer_side(tmp_path, disk_side="B")

    disk = build(tmp_path, first, second)

    assert [info_of(disk, index)[0x15] for index in range(2)] == [0, 1]


def test_a_manifest_file_is_built_by_its_own_schema(tmp_path: Path) -> None:
    path = tmp_path / "diskinfo.json"
    path.write_text(json.dumps({"sides": [packer_side(tmp_path)]}), encoding="utf-8")

    data = build_manifest_file(path)

    disk, findings = decode(data)
    assert [finding.code for finding in findings] == []
    assert info_of(disk) == DEFAULT_INFO


def test_a_manifest_whose_sides_are_not_a_list_is_not_recognised() -> None:
    recognised = FdsPackerManifest.recognises({"sides": "A"})

    assert recognised is False


def test_a_manifest_that_is_not_an_object_is_not_recognised() -> None:
    recognised = FdsPackerManifest.recognises(["sides"])

    assert recognised is False


def test_a_number_that_does_not_parse_is_refused(tmp_path: Path) -> None:
    side = packer_side(tmp_path, game_version="0xZZ")

    with pytest.raises(ValueError, match=r"game_version '0xZZ' is not a number"):
        build(tmp_path, side)


def test_a_game_name_outside_latin_1_is_refused(tmp_path: Path) -> None:
    side = packer_side(tmp_path, game_name="\u6f22")

    with pytest.raises(ValueError, match=r"outside Latin-1"):
        build(tmp_path, side)


def test_a_game_name_that_is_not_text_is_refused(tmp_path: Path) -> None:
    side = packer_side(tmp_path, game_name=5)

    with pytest.raises(ValueError, match=r"game_name is 5"):
        build(tmp_path, side)


def test_a_file_larger_than_a_header_can_state_is_refused(tmp_path: Path) -> None:
    entry = packer_file(tmp_path, 0, data=payload_of(tmp_path, "huge.bin", 0x10000))

    with pytest.raises(ValueError, match=r"holds 65536 bytes"):
        build(tmp_path, packer_side(tmp_path, files=[entry]))


def test_a_manifest_file_holding_a_list_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "diskinfo.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match=r"a manifest is a JSON object"):
        build_manifest_file(path)
