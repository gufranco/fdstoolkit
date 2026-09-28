from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from fdstoolkit.build.fdspacker import FdsPackerManifest
from fdstoolkit.build.fdspacker_export import MANIFEST_NAME, FdsPackerExport
from fdstoolkit.build.manifest import build_manifest_file
from fdstoolkit.cli.main import app
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side

runner = CliRunner()


def payload_of(tmp_path: Path, name: str, size: int) -> str:
    (tmp_path / name).write_bytes(hashlib.shake_256(name.encode()).digest(size))
    return name


def packer_file(tmp_path: Path, number: int, **fields: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "file_number": number,
        "file_indicate_code": number + 0x10,
        "file_name": f"F{number}",
        "file_address": "$6000",
        "file_kind": "Program",
        "data": payload_of(tmp_path, f"in{number}.bin", 24 + number),
    }
    return {**entry, **fields}


def unusual_side(tmp_path: Path) -> dict[str, Any]:
    return {
        "licensee_code": "$A4",
        "game_name": "Z\0",
        "game_type": "$07",
        "disk_side": "B",
        "disk_type": "$05",
        "unknown02": "$00",
        "unknown07": "$62",
        "manufacturing_date": "2026-09-28",
        "country_code": "$00",
        "rewritten_date": "1987-01-31",
        "disk_writer_serial_number": "$ABCD",
        "unknown18": "$07",
        "disk_rewrite_count": 42,
        "disk_type_other": "BlueDisk",
        "disk_version": "$03",
        "file_amount": 1,
        "files": [
            packer_file(tmp_path, 0, file_name="KYODAKU-"),
            packer_file(tmp_path, 1, file_kind="$09", file_name="SEC\0RET"),
            packer_file(tmp_path, 2, file_kind="NameTable", file_name="PAD  "),
        ],
    }


def image_of(tmp_path: Path, *sides: dict[str, Any]) -> bytes:
    return FdsPackerManifest.parse({"sides": list(sides)}, root=tmp_path).build()


def write_export(export: FdsPackerExport, directory: Path) -> Path:
    for relative, data in export.files:
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = directory / MANIFEST_NAME
    manifest.write_text(export.text(), encoding="utf-8")
    return manifest


def export_of(image: bytes) -> FdsPackerExport:
    disk, _ = decode(image)
    return FdsPackerExport.of(disk)


def replaced_info(image: bytes, offset: int, value: bytes) -> bytes:
    changed = bytearray(image)
    changed[offset : offset + len(value)] = value
    return bytes(changed)


def test_extract_then_build_gives_back_the_same_bytes(tmp_path: Path) -> None:
    image = image_of(tmp_path, unusual_side(tmp_path), {**unusual_side(tmp_path), "disk_side": "A"})
    manifest = write_export(export_of(image), tmp_path / "out")

    rebuilt = build_manifest_file(manifest)

    assert rebuilt == image


def test_names_are_written_where_fdspacker_has_them(tmp_path: Path) -> None:
    image = image_of(tmp_path, unusual_side(tmp_path))

    side = json.loads(export_of(image).text())["sides"][0]

    assert (side["disk_side"], side["disk_type"], side["disk_type_other"]) == (
        "B",
        "$05",
        "BlueDisk",
    )
    assert [item["file_kind"] for item in side["files"]] == ["Program", "$09", "NameTable"]


def test_fields_are_written_in_fdspacker_notation(tmp_path: Path) -> None:
    image = image_of(tmp_path, unusual_side(tmp_path))

    side = json.loads(export_of(image).text())["sides"][0]

    assert side["licensee_code"] == "$A4"
    assert side["game_type"] == "$07"
    assert side["disk_writer_serial_number"] == "$ABCD"
    assert side["manufacturing_date"] == "2026-09-28"
    assert side["disk_rewrite_count"] == 42


def test_a_printable_game_type_is_written_as_its_character(tmp_path: Path) -> None:
    image = image_of(tmp_path, {**unusual_side(tmp_path), "game_type": "E"})

    side = json.loads(export_of(image).text())["sides"][0]

    assert side["game_type"] == "E"


def test_an_empty_game_name_and_empty_dates_are_written_as_null(tmp_path: Path) -> None:
    side = {**unusual_side(tmp_path), "game_name": None}
    del side["manufacturing_date"]
    image = image_of(tmp_path, side)

    written = json.loads(export_of(image).text())["sides"][0]

    assert (written["game_name"], written["manufacturing_date"]) == (None, None)


def test_the_declared_file_amount_is_kept_apart_from_the_files(tmp_path: Path) -> None:
    image = image_of(tmp_path, unusual_side(tmp_path))

    side = json.loads(export_of(image).text())["sides"][0]

    assert (side["file_amount"], len(side["files"])) == (1, 3)


def test_data_files_are_named_by_side_position_and_kind(tmp_path: Path) -> None:
    image = image_of(tmp_path, unusual_side(tmp_path))

    paths = [relative for relative, _ in export_of(image).files]

    assert paths == ["side0-00-KYODAKU-.prg", "side0-01-SEC_RET.bin", "side0-02-PAD.nt"]


def test_a_disk_without_the_nintendo_string_is_refused(tmp_path: Path) -> None:
    image = replaced_info(image_of(tmp_path, unusual_side(tmp_path)), 0x01, b"*BYPASS-HVC-X*")

    with pytest.raises(ValueError, match=r"side 1 .*verification string"):
        export_of(image)


def test_a_date_that_is_not_a_date_is_refused(tmp_path: Path) -> None:
    image = replaced_info(
        image_of(tmp_path, unusual_side(tmp_path)), 0x1F, bytes([0x61, 0x13, 0x01])
    )

    with pytest.raises(ValueError, match=r"manufacturing_date holds 61 13 01"):
        export_of(image)


def test_a_date_whose_digits_do_not_round_trip_is_refused(tmp_path: Path) -> None:
    image = replaced_info(
        image_of(tmp_path, unusual_side(tmp_path)), 0x2C, bytes([0x6A, 0x01, 0x01])
    )

    with pytest.raises(ValueError, match=r"rewritten_date"):
        export_of(image)


def test_a_rewrite_count_fdspacker_reads_as_zero_is_refused(tmp_path: Path) -> None:
    image = replaced_info(image_of(tmp_path, unusual_side(tmp_path)), 0x34, bytes([0xFF]))

    with pytest.raises(ValueError, match=r"rewrite count byte is 0xff"):
        export_of(image)


def test_a_header_whose_size_disagrees_with_its_data_is_refused(tmp_path: Path) -> None:
    disk, _ = decode(image_of(tmp_path, unusual_side(tmp_path)))
    side = disk.sides[0]
    short = Block(kind=BlockKind.FILE_DATA, payload=bytes([BlockKind.FILE_DATA, 0xEA]))
    blocks = (*side.blocks[:3], short, *side.blocks[4:])
    changed = Disk(sides=(Side(blocks=blocks, tail=b"", capacity=side.capacity),))

    with pytest.raises(ValueError, match=r"file 1 states 24 bytes and holds 1"):
        FdsPackerExport.of(changed)


def test_bytes_after_the_last_block_are_refused(tmp_path: Path) -> None:
    disk, _ = decode(image_of(tmp_path, unusual_side(tmp_path)))
    side = disk.sides[0]
    tailed = Disk(sides=(Side(blocks=side.blocks, tail=b"\x01", capacity=side.capacity),))

    with pytest.raises(ValueError, match=r"bytes after its last block"):
        FdsPackerExport.of(tailed)


def test_a_header_without_its_data_is_refused(tmp_path: Path) -> None:
    disk, _ = decode(image_of(tmp_path, unusual_side(tmp_path)))
    side = disk.sides[0]
    cut = Disk(sides=(Side(blocks=side.blocks[:3], tail=b"", capacity=side.capacity),))

    with pytest.raises(ValueError, match=r"not header and data pairs"):
        FdsPackerExport.of(cut)


def test_a_side_that_does_not_open_with_the_disk_information_is_refused() -> None:
    amount = Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([BlockKind.FILE_AMOUNT, 0]))
    disk = Disk(sides=(Side(blocks=(amount,), tail=b"", capacity=65500),))

    with pytest.raises(ValueError, match=r"does not open with a disk information"):
        FdsPackerExport.of(disk)


def test_a_disk_left_unwritten_by_the_toolkit_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "manifest.json"
    main = {"name": "MAIN", "path": payload_of(tmp_path, "main.prg", 40)}
    source.write_text(
        json.dumps({"game_name": "TST", "sides": [{"files": [main]}]}), encoding="utf-8"
    )
    image = build_manifest_file(source)

    with pytest.raises(ValueError, match=r"rewritten_date holds ff ff ff"):
        export_of(image)


def test_extract_with_an_fdspacker_manifest_writes_a_rebuildable_directory(tmp_path: Path) -> None:
    image = image_of(tmp_path, unusual_side(tmp_path))
    source = tmp_path / "source.fds"
    source.write_bytes(image)
    out = tmp_path / "unpacked"

    result = runner.invoke(app, ["extract", str(source), "-d", str(out), "--manifest", "fdspacker"])

    assert result.exit_code == 0
    assert "diskinfo.json" in result.stdout
    assert build_manifest_file(out / MANIFEST_NAME) == image


def test_extract_with_a_manifest_refuses_to_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.fds"
    source.write_bytes(image_of(tmp_path, unusual_side(tmp_path)))
    out = tmp_path / "unpacked"
    out.mkdir()
    (out / MANIFEST_NAME).write_text("{}", encoding="utf-8")

    result = runner.invoke(app, ["extract", str(source), "-d", str(out), "--manifest", "fdspacker"])

    assert result.exit_code == 1
    assert "--force" in result.stdout
    assert sorted(path.name for path in out.iterdir()) == [MANIFEST_NAME]


def test_extract_says_why_a_disk_has_no_fdspacker_manifest(tmp_path: Path) -> None:
    image = replaced_info(image_of(tmp_path, unusual_side(tmp_path)), 0x34, bytes([0xFF]))
    source = tmp_path / "source.fds"
    source.write_bytes(image)

    result = runner.invoke(
        app, ["extract", str(source), "-d", str(tmp_path / "out"), "--manifest", "fdspacker"]
    )

    assert result.exit_code == 1
    assert "rewrite count" in result.stdout
