from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fdstoolkit.edit.recipes import RECIPE_VERSION, load_recipes, recipes_for
from fdstoolkit.edit.saves import SaveRecipe


def recipe_file(tmp_path: Path, **overrides: Any) -> Path:
    payload: dict[str, Any] = {
        "version": RECIPE_VERSION,
        "recipes": [
            {
                "game_name": "SMB",
                "game_version": 0,
                "side": 0,
                "position": 1,
                "fill": 0,
                "source": "measured against two dumps",
            }
        ],
    }
    payload.update(overrides)
    path = tmp_path / "recipes.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_recipe_file_loads_every_entry(tmp_path: Path) -> None:
    recipes = load_recipes(recipe_file(tmp_path))

    assert len(recipes) == 1
    assert recipes[0].game_name == "SMB"
    assert recipes[0].position == 1


def test_a_recipe_carries_its_fill_byte(tmp_path: Path) -> None:
    assert load_recipes(recipe_file(tmp_path))[0].fill == 0


def test_a_file_of_the_wrong_version_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="version"):
        load_recipes(recipe_file(tmp_path, version=99))


def test_a_file_without_recipes_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no recipes"):
        load_recipes(recipe_file(tmp_path, recipes=[]))


def test_a_recipe_without_a_source_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "unsourced.json"
    path.write_text(
        json.dumps(
            {
                "version": RECIPE_VERSION,
                "recipes": [
                    {"game_name": "SMB", "game_version": 0, "side": 0, "position": 0, "fill": 0}
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source"):
        load_recipes(path)


def test_a_fill_outside_a_byte_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad-fill.json"
    path.write_text(
        json.dumps(
            {
                "version": RECIPE_VERSION,
                "recipes": [
                    {
                        "game_name": "SMB",
                        "game_version": 0,
                        "side": 0,
                        "position": 0,
                        "fill": 300,
                        "source": "x",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="between 0 and 255"):
        load_recipes(path)


def test_recipes_are_selected_by_game_and_version() -> None:
    recipes = (
        SaveRecipe(game_name="SMB", game_version=0, side=0, position=1, fill=0),
        SaveRecipe(game_name="ZEL", game_version=0, side=0, position=1, fill=0),
    )

    assert [entry.game_name for entry in recipes_for(recipes, game_name="SMB")] == ["SMB"]


def test_selecting_a_game_that_is_absent_gives_nothing() -> None:
    recipes = (SaveRecipe(game_name="SMB", game_version=0, side=0, position=1, fill=0),)

    assert recipes_for(recipes, game_name="ZEL") == ()
