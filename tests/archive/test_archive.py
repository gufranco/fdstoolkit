from __future__ import annotations

import io
import zipfile
from typing import TYPE_CHECKING

import pytest

from fdstoolkit.core.archive import ArchiveError, ArchiveKind, member_names, read_members

if TYPE_CHECKING:
    from faker import Faker

LIMIT = 64


def kind_of(fake: Faker) -> ArchiveKind:
    return ArchiveKind(what=f"the {fake.word()} archive", beyond=f"any {fake.word()} file")


def zipped(members: dict[str, bytes], *, folder: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        if folder:
            archive.writestr(zipfile.ZipInfo(f"{folder}/"), b"")
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_member_names_lists_files_and_leaves_out_folders(fake: Faker) -> None:
    # Arrange
    names = [fake.unique.file_name(extension="bin") for _ in range(3)]
    data = zipped({name: fake.binary(length=8) for name in names}, folder=fake.word())

    # Act
    listed = member_names(data, kind_of(fake))

    # Assert
    assert listed == tuple(names)


def test_read_members_returns_the_named_files_and_skips_absent_ones(fake: Faker) -> None:
    # Arrange
    present, absent = fake.unique.file_name(), fake.unique.file_name()
    content = fake.binary(length=LIMIT)
    data = zipped({present: content})

    # Act
    found = read_members(data, [present, absent], limit=LIMIT, kind=kind_of(fake))

    # Assert
    assert found == {present: content}


def test_a_member_over_the_limit_is_refused_by_name(fake: Faker) -> None:
    # Arrange
    name = fake.file_name()
    kind = kind_of(fake)
    data = zipped({name: fake.binary(length=LIMIT + 1)})

    # Act
    with pytest.raises(ArchiveError) as raised:
        read_members(data, [name], limit=LIMIT, kind=kind)

    # Assert
    assert str(raised.value) == f"{name} is larger than {kind.beyond}"


def test_bytes_that_are_not_a_zip_are_refused_naming_the_archive(fake: Faker) -> None:
    # Arrange
    kind = kind_of(fake)

    # Act
    with pytest.raises(ArchiveError) as raised:
        member_names(fake.binary(length=LIMIT), kind)

    # Assert
    assert str(raised.value) == f"{kind.what} is not a zip archive"


def test_a_member_whose_bytes_changed_is_reported_damaged(fake: Faker) -> None:
    # Arrange
    name = fake.file_name()
    kind = kind_of(fake)
    content = fake.binary(length=LIMIT)
    data = bytearray(zipped({name: content}))
    data[data.find(content)] ^= 0xFF

    # Act
    with pytest.raises(ArchiveError) as raised:
        read_members(bytes(data), [name], limit=LIMIT, kind=kind)

    # Assert
    assert str(raised.value).startswith(f"{name} is damaged inside {kind.what}: ")
