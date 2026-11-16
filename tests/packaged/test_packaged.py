from __future__ import annotations

import io
import json
import zipfile
from typing import TYPE_CHECKING

import pytest

from fdstoolkit.build.fdspacker import FdsPackerManifest
from fdstoolkit.build.fdspacker_export import MANIFEST_NAME, FdsPackerExport
from fdstoolkit.build.fields import FieldError
from fdstoolkit.build.packaged import MAX_MEMBERS, PackagedBuildError, build_packaged
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.archive import ArchiveError
from fdstoolkit.core.files import extract_files

if TYPE_CHECKING:
    from pathlib import Path

    from faker import Faker
from fakes import game_name, seeded

FAKE = seeded(__name__)
GAME = game_name(FAKE)

FILE_NAME_LENGTH = 8


def zipped(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def manifest(path: str, name: str) -> bytes:
    side = {"side": 0, "files": [{"name": name, "path": path}]}
    return json.dumps({"game_name": GAME, "sides": [side]}).encode()


def disk_name(fake: Faker) -> str:
    return fake.pystr(min_chars=FILE_NAME_LENGTH, max_chars=FILE_NAME_LENGTH).upper()


def test_a_zipped_folder_builds_from_the_files_it_carries(fake: Faker) -> None:
    # Arrange
    content = fake.binary(length=fake.pyint(min_value=1, max_value=512))
    member = f"{fake.word()}/{fake.file_name(extension='prg')}"
    upload = zipped({"disk.json": manifest(member, disk_name(fake)), member: content})

    # Act
    image = build_packaged(upload)

    # Assert
    disk, _ = decode(image)
    assert [entry.data for entry in extract_files(disk)] == [content]


def test_an_fdspacker_export_zipped_builds_the_disk_it_came_from(
    tmp_path: Path, fake: Faker
) -> None:
    # Arrange
    (tmp_path / "a.bin").write_bytes(fake.binary(length=fake.pyint(min_value=1, max_value=512)))
    side = {"game_name": GAME, "file_amount": 1, "files": [{"file_name": "A", "data": "a.bin"}]}
    original = FdsPackerManifest.parse({"sides": [side]}, root=tmp_path).build()
    export = FdsPackerExport.of(decode(original)[0])
    upload = zipped({MANIFEST_NAME: export.text().encode(), **dict(export.files)})

    # Act
    image = build_packaged(upload)

    # Assert
    assert image == original


def test_a_manifest_alone_builds_a_disk_without_files() -> None:
    # Arrange
    upload = json.dumps({"game_name": GAME, "sides": [{"files": []}]}).encode()

    # Act
    image = build_packaged(upload)

    # Assert
    disk, _ = decode(image)
    assert extract_files(disk) == ()


def test_a_manifest_naming_an_absolute_path_is_refused(tmp_path: Path, fake: Faker) -> None:
    # Arrange
    outside = tmp_path / fake.file_name()
    outside.write_bytes(fake.binary(length=16))
    upload = manifest(str(outside), disk_name(fake))

    # Act
    with pytest.raises(FieldError) as raised:
        build_packaged(upload)

    # Assert
    assert str(raised.value) == (
        f"side 1 file 1: {outside} lies outside the uploaded folder, so it is not read"
    )


def test_a_manifest_climbing_out_of_the_folder_is_refused(fake: Faker) -> None:
    # Arrange
    climbing = f"../{fake.file_name()}"
    upload = zipped({"disk.json": manifest(climbing, disk_name(fake))})

    # Act
    with pytest.raises(FieldError) as raised:
        build_packaged(upload)

    # Assert
    assert str(raised.value) == (
        f"side 1 file 1: {climbing} lies outside the uploaded folder, so it is not read"
    )


def test_an_fdspacker_manifest_naming_an_absolute_path_is_refused(
    tmp_path: Path, fake: Faker
) -> None:
    # Arrange
    outside = tmp_path / fake.file_name()
    outside.write_bytes(fake.binary(length=16))
    side = {"game_name": GAME, "file_amount": 1, "files": [{"data": str(outside)}]}
    upload = json.dumps({"sides": [side]}).encode()

    # Act
    with pytest.raises(FieldError) as raised:
        build_packaged(upload)

    # Assert
    assert str(raised.value) == (
        f"side 1 file 1: {outside} lies outside the uploaded folder, so it is not read"
    )


def test_a_member_whose_name_climbs_out_is_refused(fake: Faker) -> None:
    # Arrange
    climbing = f"../{fake.file_name()}"
    upload = zipped({"disk.json": manifest("a.prg", disk_name(fake)), climbing: b"\x00"})

    # Act
    with pytest.raises(FieldError) as raised:
        build_packaged(upload)

    # Assert
    assert str(raised.value) == (
        f"the uploaded folder: {climbing} lies outside the uploaded folder, so it is not read"
    )


@pytest.mark.parametrize("count", [0, 2])
def test_a_zip_without_exactly_one_manifest_is_refused(count: int, fake: Faker) -> None:
    # Arrange
    names = [f"{fake.unique.word()}.json" for _ in range(count)]
    upload = zipped(dict.fromkeys(names, b"{}") | {"a.prg": b"\x00"})

    # Act
    with pytest.raises(PackagedBuildError) as raised:
        build_packaged(upload)

    # Assert
    assert str(raised.value) == (
        f"the zip holds {count} JSON manifests at its top level, and a build reads exactly one"
    )


def test_a_zip_with_too_many_members_is_refused() -> None:
    # Arrange
    upload = zipped({f"{index}.bin": b"\x00" for index in range(MAX_MEMBERS + 1)})

    # Act
    with pytest.raises(PackagedBuildError) as raised:
        build_packaged(upload)

    # Assert
    assert str(raised.value) == (
        f"the zip holds {MAX_MEMBERS + 1} files, more than the {MAX_MEMBERS} two sides of a "
        "disk can carry with their manifest"
    )


def test_a_damaged_zip_is_refused_as_the_manifest_folder() -> None:
    # Arrange
    upload = b"PK\x03\x04" + bytes(32)

    # Act
    with pytest.raises(ArchiveError) as raised:
        build_packaged(upload)

    # Assert
    assert str(raised.value) == "the manifest folder is not a zip archive"
