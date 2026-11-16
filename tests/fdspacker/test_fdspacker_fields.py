from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdspacker_kit import DEFAULT_INFO, build, info_of, packer_file, packer_side, payload_of

from fdstoolkit.build.fdspacker import FdsPackerError, FdsPackerManifest
from fdstoolkit.build.manifest import ManifestShapeError, build_manifest_file
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.blocks import FileHeader, FileKind
from fdstoolkit.core.disk import SIDE_SIZE
from fdstoolkit.core.files import extract_files


def test_dates_are_written_as_showa_years_in_bcd(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, manufacturing_date="2022-09-21T00:00:00")

    # Act
    info = info_of(build(tmp_path, side))

    # Assert
    assert info[0x1F:0x22] == bytes([0x97, 0x09, 0x21])


def test_a_date_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, rewritten_date="1987-02-30")

    # Act
    with pytest.raises(ValueError, match=r"rewritten_date 1987-02-30") as raised:
        build(tmp_path, side)

    # Assert
    assert raised.type is FdsPackerError


def test_a_date_before_showa_is_refused(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, manufacturing_date="1920-01-01")

    # Act
    with pytest.raises(ValueError, match=r"manufacturing_date 1920-01-01") as raised:
        build(tmp_path, side)

    # Assert
    assert raised.type is FdsPackerError


def test_a_date_in_another_shape_is_refused(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, manufacturing_date="21/09/2022")

    # Act
    with pytest.raises(ValueError, match=r"YYYY-MM-DD") as raised:
        build(tmp_path, side)

    # Assert
    assert raised.type is FdsPackerError


def test_a_null_game_name_leaves_the_name_empty(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, game_name=None)

    # Act
    info = info_of(build(tmp_path, side))

    # Assert
    assert info[0x10:0x13] == bytes(3)


def test_a_short_game_name_is_padded_with_zeros(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, game_name="AB")

    # Act
    info = info_of(build(tmp_path, side))

    # Assert
    assert info[0x10:0x13] == b"AB\x00"


def test_a_side_without_a_game_name_is_refused(tmp_path: Path) -> None:
    # Arrange
    side: dict[str, object] = {"file_amount": 0, "disk_side": "A", "files": []}

    # Act
    with pytest.raises(ValueError, match=r"side 1 has no game_name") as raised:
        build(tmp_path, side)

    # Assert
    assert raised.type is FdsPackerError


def test_a_game_name_longer_than_three_is_refused(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, game_name="GAMENAME")

    # Act
    with pytest.raises(ValueError, match=r"game_name 'GAMENAME' is longer than 3") as raised:
        build(tmp_path, side)

    # Assert
    assert raised.type is FdsPackerError


def test_file_amount_is_written_as_given(tmp_path: Path) -> None:
    # Arrange
    files = [packer_file(tmp_path, number) for number in range(3)]
    side = packer_side(tmp_path, file_amount=2, files=files)
    disk = build(tmp_path, side)

    # Act
    listed = extract_files(disk)

    # Assert
    assert disk.sides[0].declared_file_count == 2
    assert [entry.hidden for entry in listed] == [False, False, True]


def test_a_side_without_file_amount_declares_no_files(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path)
    del side["file_amount"]

    # Act
    disk = build(tmp_path, side)

    # Assert
    assert disk.sides[0].declared_file_count == 0


def test_a_file_header_carries_the_listed_fields(tmp_path: Path) -> None:
    # Arrange
    entry = packer_file(
        tmp_path,
        4,
        file_indicate_code=9,
        file_name="KYODAKU",
        file_address="$2800",
        file_kind="Character",
    )
    disk = build(tmp_path, packer_side(tmp_path, files=[entry]))

    # Act
    header = FileHeader.parse(disk.sides[0].blocks[2].payload)

    # Assert
    assert (header.number, header.file_id) == (4, 9)
    assert header.raw_name == b"KYODAKU\x00"
    assert (header.address, header.size, header.kind) == (0x2800, 20, FileKind.CHARACTER)


def test_a_file_without_a_name_is_named_filename(tmp_path: Path) -> None:
    # Arrange
    entry = packer_file(tmp_path, 0)
    del entry["file_name"]
    disk = build(tmp_path, packer_side(tmp_path, files=[entry]))

    # Act
    header = FileHeader.parse(disk.sides[0].blocks[2].payload)

    # Assert
    assert header.raw_name == b"FILENAME"


def test_a_file_name_longer_than_eight_is_refused(tmp_path: Path) -> None:
    # Arrange
    entry = packer_file(tmp_path, 0, file_name="TOOLONGNAME")

    # Act
    with pytest.raises(ValueError, match=r"file_name 'TOOLONGNAME' is longer than 8") as raised:
        build(tmp_path, packer_side(tmp_path, files=[entry]))

    # Assert
    assert raised.type is FdsPackerError


def test_a_null_file_name_is_refused(tmp_path: Path) -> None:
    # Arrange
    entry = packer_file(tmp_path, 0, file_name=None)

    # Act
    with pytest.raises(ValueError, match=r"file_name") as raised:
        build(tmp_path, packer_side(tmp_path, files=[entry]))

    # Assert
    assert raised.type is FdsPackerError


def test_a_file_without_data_is_refused(tmp_path: Path) -> None:
    # Arrange
    entry = packer_file(tmp_path, 0)
    del entry["data"]

    # Act
    with pytest.raises(ValueError, match=r"side 1 file 1 has no data") as raised:
        build(tmp_path, packer_side(tmp_path, files=[entry]))

    # Assert
    assert raised.type is FdsPackerError


def test_a_file_whose_data_is_missing_on_disk_is_refused(tmp_path: Path) -> None:
    # Arrange
    entry = packer_file(tmp_path, 0, data="absent.bin")

    # Act
    with pytest.raises(ValueError, match=r"file not found: .*absent\.bin") as raised:
        build(tmp_path, packer_side(tmp_path, files=[entry]))

    # Assert
    assert raised.type is FdsPackerError


def test_a_manifest_mixing_both_schemas_is_refused(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, side=0)

    # Act
    with pytest.raises(ValueError, match=r"mixes .*side") as raised:
        build(tmp_path, side)

    # Assert
    assert raised.type is FdsPackerError


def test_a_manifest_without_sides_is_refused(tmp_path: Path) -> None:
    # Arrange
    payload: dict[str, object] = {"sides": []}

    # Act
    with pytest.raises(ValueError, match=r"at least one side") as raised:
        FdsPackerManifest.parse(payload, root=tmp_path)

    # Assert
    assert raised.type is FdsPackerError


def test_a_side_that_overflows_the_disk_is_refused(tmp_path: Path) -> None:
    # Arrange
    entry = packer_file(tmp_path, 0, data=payload_of(tmp_path, "big.bin", SIDE_SIZE))

    # Act
    with pytest.raises(ValueError, match=r"does not fit") as raised:
        build(tmp_path, packer_side(tmp_path, files=[entry]))

    # Assert
    assert raised.type is FdsPackerError


def test_every_listed_side_is_built(tmp_path: Path) -> None:
    # Arrange
    first = packer_side(tmp_path, disk_side="A")
    second = packer_side(tmp_path, disk_side="B")

    # Act
    disk = build(tmp_path, first, second)

    # Assert
    assert [info_of(disk, index)[0x15] for index in range(2)] == [0, 1]


def test_a_manifest_file_is_built_by_its_own_schema(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "diskinfo.json"
    path.write_text(json.dumps({"sides": [packer_side(tmp_path)]}), encoding="utf-8")
    data = build_manifest_file(path)

    # Act
    disk, findings = decode(data)

    # Assert
    assert [finding.code for finding in findings] == []
    assert info_of(disk) == DEFAULT_INFO


def test_a_manifest_whose_sides_are_not_a_list_is_not_recognised() -> None:
    # Arrange
    payload = {"sides": "A"}

    # Act
    recognised = FdsPackerManifest.recognises(payload)

    # Assert
    assert recognised is False


def test_a_manifest_that_is_not_an_object_is_not_recognised() -> None:
    # Arrange
    payload = ["sides"]

    # Act
    recognised = FdsPackerManifest.recognises(payload)

    # Assert
    assert recognised is False


def test_a_number_that_does_not_parse_is_refused(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, game_version="0xZZ")

    # Act
    with pytest.raises(ValueError, match=r"game_version '0xZZ' is not a number") as raised:
        build(tmp_path, side)

    # Assert
    assert raised.type is FdsPackerError


def test_a_game_name_outside_latin_1_is_refused(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, game_name="\u6f22")

    # Act
    with pytest.raises(ValueError, match=r"outside Latin-1") as raised:
        build(tmp_path, side)

    # Assert
    assert raised.type is FdsPackerError


def test_a_game_name_that_is_not_text_is_refused(tmp_path: Path) -> None:
    # Arrange
    side = packer_side(tmp_path, game_name=5)

    # Act
    with pytest.raises(ValueError, match=r"game_name is 5") as raised:
        build(tmp_path, side)

    # Assert
    assert raised.type is FdsPackerError


def test_a_file_larger_than_a_header_can_state_is_refused(tmp_path: Path) -> None:
    # Arrange
    entry = packer_file(tmp_path, 0, data=payload_of(tmp_path, "huge.bin", 0x10000))

    # Act
    with pytest.raises(ValueError, match=r"holds 65536 bytes") as raised:
        build(tmp_path, packer_side(tmp_path, files=[entry]))

    # Assert
    assert raised.type is FdsPackerError


def test_a_manifest_file_holding_a_list_is_refused(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "diskinfo.json"
    path.write_text("[]", encoding="utf-8")

    # Act
    with pytest.raises(ValueError, match=r"a manifest is a JSON object") as raised:
        build_manifest_file(path)

    # Assert
    assert raised.type is ManifestShapeError
