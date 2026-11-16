from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fakes import game_name, seeded
from main_kit import attach, runner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app

if TYPE_CHECKING:
    import pytest

FAKE = seeded(__name__)
GAME = game_name(FAKE)


def test_a_quick_surface_test_grades_a_good_scratch_disk_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    image = tmp_path / "scratch.fds"
    image.write_bytes(blank_image(sides=1, headered=False, formatted=True, game_name=GAME))
    attach(monkeypatch, image)

    # Act
    result = runner.invoke(app, ["surface", "--quick", "--yes"])

    # Assert
    assert result.exit_code == 0, result.output
    assert result.stdout.rstrip().endswith("grade clean")
