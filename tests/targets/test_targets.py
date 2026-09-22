from __future__ import annotations

import zlib
from pathlib import Path

import pytest

from fdstk.build.blank import blank_image
from fdstk.build.targets import TARGETS, export_for, swap_warnings
from fdstk.codecs.fds import SIDE_SIZE, decode
from fdstk.core.blocks import FileKind
from fdstk.core.disk import Disk
from fdstk.edit.files import FileSpec, insert_file
from fdstk.identify import firmware


def game(*, sides: int = 2) -> Disk:
    disk, _ = decode(blank_image(sides=sides, headered=False, formatted=True, game_name="SMB"))
    for side in range(sides):
        disk = insert_file(
            disk,
            side=side,
            spec=FileSpec(name="MAIN", address=0x6000, kind=FileKind.PROGRAM, data=b"\x01" * 8),
        )
    return disk


@pytest.fixture
def bios(monkeypatch: pytest.MonkeyPatch) -> bytes:
    data = bytes([0x5A]) * firmware.BIOS_SIZE
    crc = f"{zlib.crc32(data):08x}"
    monkeypatch.setattr(
        firmware,
        "KNOWN_REVISIONS",
        {crc: firmware.Revision(name="Rev 01A", crc32=crc, sha1="0" * 40, mame_name="x")},
    )
    return data


def test_every_target_names_its_source() -> None:
    assert all(target.source.startswith("https://") for target in TARGETS.values())


def test_the_nt_mini_gets_a_headerless_image(tmp_path: Path) -> None:
    written = export_for(game(), target="nt-mini", directory=tmp_path, stem="Game")

    image = tmp_path / "Game.fds"
    assert image in written
    assert len(image.read_bytes()) == 2 * SIDE_SIZE


def test_ares_gets_one_file_per_side(tmp_path: Path) -> None:
    written = export_for(game(), target="ares", directory=tmp_path, stem="Game")

    assert sorted(path.name for path in written) == ["disk1.sideA", "disk1.sideB"]
    assert all(path.parent == tmp_path / "Game" for path in written)


def test_the_bios_goes_where_the_nt_mini_looks(tmp_path: Path, bios: bytes) -> None:
    export_for(game(), target="nt-mini", directory=tmp_path, stem="Game", bios=bios)

    assert (tmp_path / "BIOS" / "fds.bin").read_bytes() == bios


def test_the_bios_goes_where_mister_looks(tmp_path: Path, bios: bytes) -> None:
    export_for(game(), target="mister", directory=tmp_path, stem="Game", bios=bios)

    assert (tmp_path / "boot0.rom").read_bytes() == bios


def test_the_bios_goes_where_the_everdrive_looks(tmp_path: Path, bios: bytes) -> None:
    export_for(game(), target="everdrive-n8-pro", directory=tmp_path, stem="Game", bios=bios)

    assert (tmp_path / "EDN8" / "syscore" / "disksys.rom").read_bytes() == bios


def test_a_bios_inside_a_larger_dump_is_extracted_first(tmp_path: Path, bios: bytes) -> None:
    wrapped = bytes(0x6000) + bios + bytes(0x2000)

    export_for(game(), target="mister", directory=tmp_path, stem="Game", bios=wrapped)

    assert (tmp_path / "boot0.rom").read_bytes() == bios


@pytest.mark.usefixtures("bios")
def test_an_unknown_bios_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no known BIOS"):
        export_for(game(), target="mister", directory=tmp_path, stem="Game", bios=bytes(0x2000))


def test_a_target_with_no_bios_location_refuses_a_bios(tmp_path: Path, bios: bytes) -> None:
    with pytest.raises(ValueError, match="does not take a BIOS"):
        export_for(game(), target="ares", directory=tmp_path, stem="Game", bios=bios)


def test_an_unknown_target_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown target"):
        export_for(game(), target="powerpak", directory=tmp_path, stem="Game")


def test_an_existing_file_is_not_overwritten(tmp_path: Path) -> None:
    export_for(game(), target="nt-mini", directory=tmp_path, stem="Game")

    with pytest.raises(FileExistsError):
        export_for(game(), target="nt-mini", directory=tmp_path, stem="Game")


def test_an_existing_file_can_be_overwritten_when_asked(tmp_path: Path) -> None:
    export_for(game(), target="nt-mini", directory=tmp_path, stem="Game")

    written = export_for(game(), target="nt-mini", directory=tmp_path, stem="Game", force=True)

    assert written


def test_a_known_swap_exception_is_reported_for_its_target() -> None:
    warnings = swap_warnings("Doremikko (Japan)", target="nt-mini")

    assert len(warnings) == 1
    assert "Doremikko" in warnings[0]


def test_a_swap_exception_is_matched_regardless_of_case() -> None:
    assert swap_warnings("gall force - eternal story (japan)", target="mister")


def test_a_title_off_the_list_has_no_warning() -> None:
    assert swap_warnings("Super Mario Bros. (Japan)", target="nt-mini") == ()


def test_a_target_without_a_list_has_no_warning() -> None:
    assert swap_warnings("Doremikko (Japan)", target="ares") == ()
