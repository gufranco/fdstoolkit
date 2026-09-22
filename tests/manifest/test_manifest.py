from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fdstk.build.manifest import DiskManifest, build_from_manifest, load_manifest
from fdstk.codecs.fds import SIDE_SIZE, decode
from fdstk.core.blocks import FileKind
from fdstk.core.diskinfo import DiskInfo
from fdstk.edit.files import extract_files


def manifest_dict(tmp_path: Path) -> dict[str, Any]:
    payload = tmp_path / "main.prg"
    payload.write_bytes(bytes([0xAA]) * 16)
    return {
        "game_name": "SMB",
        "licensee": 1,
        "game_version": 0,
        "sides": [
            {
                "side": 0,
                "disk_number": 0,
                "boot_file": 0,
                "files": [
                    {
                        "name": "MAIN",
                        "address": "0x6000",
                        "kind": "program",
                        "path": str(payload),
                    }
                ],
            }
        ],
    }


def test_a_manifest_builds_a_parseable_disk(tmp_path: Path) -> None:
    data = build_from_manifest(DiskManifest.from_dict(manifest_dict(tmp_path), root=tmp_path))

    _, findings = decode(data)

    assert [finding.code for finding in findings] == []
    assert len(data) == SIDE_SIZE


def test_the_built_disk_carries_the_declared_identity(tmp_path: Path) -> None:
    data = build_from_manifest(DiskManifest.from_dict(manifest_dict(tmp_path), root=tmp_path))
    disk, _ = decode(data)
    info = DiskInfo.parse(disk.sides[0].blocks[0].payload)

    assert info.game_name == "SMB"
    assert info.licensee == 1
    assert info.is_verified


def test_the_built_disk_carries_the_declared_files(tmp_path: Path) -> None:
    data = build_from_manifest(DiskManifest.from_dict(manifest_dict(tmp_path), root=tmp_path))
    disk, _ = decode(data)
    files = extract_files(disk)

    assert [entry.name for entry in files] == ["MAIN"]
    assert files[0].address == 0x6000
    assert files[0].kind is FileKind.PROGRAM
    assert files[0].data == bytes([0xAA]) * 16


def test_a_build_carries_no_date_so_it_is_reproducible(tmp_path: Path) -> None:
    manifest = DiskManifest.from_dict(manifest_dict(tmp_path), root=tmp_path)
    disk, _ = decode(build_from_manifest(manifest))
    info = DiskInfo.parse(disk.sides[0].blocks[0].payload)

    assert info.raw("manufacturing_date") == bytes(3)
    assert info.raw("rewritten_date") == bytes(3)


def test_a_declared_date_is_written_in_bcd(tmp_path: Path) -> None:
    payload = manifest_dict(tmp_path)
    payload["manufacturing_date"] = "1986-02-15"

    disk, _ = decode(build_from_manifest(DiskManifest.from_dict(payload, root=tmp_path)))
    info = DiskInfo.parse(disk.sides[0].blocks[0].payload)

    assert info.manufacturing_date == (1986, 2, 15)


def test_two_builds_of_one_manifest_are_identical(tmp_path: Path) -> None:
    manifest = DiskManifest.from_dict(manifest_dict(tmp_path), root=tmp_path)

    assert build_from_manifest(manifest) == build_from_manifest(manifest)


def test_a_manifest_loads_from_json(tmp_path: Path) -> None:
    path = tmp_path / "disk.json"
    path.write_text(json.dumps(manifest_dict(tmp_path)), encoding="utf-8")

    manifest = load_manifest(path)

    assert manifest.game_name == "SMB"
    assert len(manifest.sides) == 1


def test_a_relative_file_path_resolves_against_the_manifest(tmp_path: Path) -> None:
    payload = manifest_dict(tmp_path)
    (tmp_path / "main.prg").write_bytes(bytes([0x01]) * 8)
    sides: list[dict[str, Any]] = payload["sides"]
    sides[0]["files"][0]["path"] = "main.prg"
    path = tmp_path / "disk.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    disk, _ = decode(build_from_manifest(load_manifest(path)))

    assert extract_files(disk)[0].data == bytes([0x01]) * 8


def test_a_missing_file_is_reported(tmp_path: Path) -> None:
    payload = manifest_dict(tmp_path)
    sides: list[dict[str, Any]] = payload["sides"]
    sides[0]["files"][0]["path"] = str(tmp_path / "nope.prg")

    with pytest.raises(ValueError, match="not found"):
        build_from_manifest(DiskManifest.from_dict(payload, root=tmp_path))


def test_a_manifest_without_sides_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one side"):
        DiskManifest.from_dict({"game_name": "SMB", "sides": []}, root=tmp_path)


def test_a_game_name_of_the_wrong_length_is_refused(tmp_path: Path) -> None:
    payload = manifest_dict(tmp_path)
    payload["game_name"] = "TOOLONG"

    with pytest.raises(ValueError, match="three characters"):
        DiskManifest.from_dict(payload, root=tmp_path)


def test_an_unknown_file_kind_is_refused(tmp_path: Path) -> None:
    payload = manifest_dict(tmp_path)
    sides: list[dict[str, Any]] = payload["sides"]
    sides[0]["files"][0]["kind"] = "sound"

    with pytest.raises(ValueError, match="unknown file kind"):
        DiskManifest.from_dict(payload, root=tmp_path)


def test_a_date_that_is_not_a_date_is_refused(tmp_path: Path) -> None:
    payload = manifest_dict(tmp_path)
    payload["manufacturing_date"] = "not-a-date"

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        DiskManifest.from_dict(payload, root=tmp_path)


def test_a_multi_side_manifest_builds_every_side(tmp_path: Path) -> None:
    payload = manifest_dict(tmp_path)
    sides: list[dict[str, Any]] = payload["sides"]
    sides.append({"side": 1, "disk_number": 0, "files": []})

    disk, _ = decode(build_from_manifest(DiskManifest.from_dict(payload, root=tmp_path)))

    assert disk.side_count == 2
    assert disk.sides[1].declared_file_count == 0


def test_a_manifest_defaults_to_the_nintendo_licence_string(tmp_path: Path) -> None:
    manifest = DiskManifest.from_dict(manifest_dict(tmp_path), root=tmp_path)

    assert manifest.boots_on_stock_hardware
    disk, _ = decode(build_from_manifest(manifest))
    info = disk.sides[0].disk_info
    assert info is not None
    assert info.verification == b"*NINTENDO-HVC*"


def test_the_licence_check_can_be_bypassed(tmp_path: Path) -> None:
    payload = manifest_dict(tmp_path)
    payload["licence"] = "bypass"

    manifest = DiskManifest.from_dict(payload, root=tmp_path)

    assert not manifest.boots_on_stock_hardware
    disk, _ = decode(build_from_manifest(manifest))
    info = disk.sides[0].disk_info
    assert info is not None
    assert info.verification == bytes(14)


def test_a_custom_licence_string_is_written_verbatim(tmp_path: Path) -> None:
    payload = manifest_dict(tmp_path)
    payload["license"] = "*HOMEBREW-FDS*"

    manifest = DiskManifest.from_dict(payload, root=tmp_path)

    assert manifest.verification == b"*HOMEBREW-FDS*"
    assert not manifest.boots_on_stock_hardware


def test_a_licence_string_of_the_wrong_length_is_refused(tmp_path: Path) -> None:
    payload = manifest_dict(tmp_path)
    payload["licence"] = "TOO SHORT"

    with pytest.raises(ValueError, match="14 characters"):
        DiskManifest.from_dict(payload, root=tmp_path)
