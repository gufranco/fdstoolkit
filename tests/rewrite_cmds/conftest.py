from __future__ import annotations

from pathlib import Path

import pytest
from fakes import game_name, seeded

from fdstoolkit.build.blank import blank_image

FAKE = seeded(__name__)
GAME = game_name(FAKE)


@pytest.fixture
def single_side(tmp_path: Path) -> Path:
    path = tmp_path / "one-side.fds"
    path.write_bytes(blank_image(sides=1, headered=False, formatted=True, game_name=GAME))
    return path


@pytest.fixture
def two_sides(tmp_path: Path) -> Path:
    path = tmp_path / "two-sides.fds"
    path.write_bytes(blank_image(sides=2, headered=False, formatted=True, game_name=GAME))
    return path
