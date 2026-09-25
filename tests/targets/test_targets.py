from __future__ import annotations

from pathlib import Path

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.targets import TARGETS, export_for, swap_warnings
from fdstoolkit.cli.common import TargetChoice
from fdstoolkit.codecs.fds import SIDE_SIZE, decode
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Disk
from fdstoolkit.edit.files import FileSpec, insert_file


def game(*, sides: int = 2) -> Disk:
    disk, _ = decode(blank_image(sides=sides, headered=False, formatted=True, game_name="SMB"))
    for side in range(sides):
        disk = insert_file(
            disk,
            side=side,
            spec=FileSpec(name="MAIN", address=0x6000, kind=FileKind.PROGRAM, data=b"\x01" * 8),
        )
    return disk


def test_every_target_names_its_source() -> None:
    assert all(target.source.startswith("https://") for target in TARGETS.values())


def test_the_nt_mini_gets_a_headerless_image(tmp_path: Path) -> None:
    written = export_for(game(), target="nt-mini", directory=tmp_path, stem="Game")

    image = tmp_path / "Game.fds"
    assert image in written
    assert len(image.read_bytes()) == 2 * SIDE_SIZE


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
    assert swap_warnings("Doremikko (Japan)", target="fceux") == ()


def test_the_command_line_offers_exactly_the_targets_the_exporter_knows() -> None:
    assert [choice.value for choice in TargetChoice] == list(TARGETS)
