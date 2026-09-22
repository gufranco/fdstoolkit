from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

from fdstoolkit.edit.saves import SaveRecipe

RECIPE_VERSION: Final = 1
BYTE_MAX: Final = 0xFF


def _entry_to_recipe(entry: dict[str, Any]) -> SaveRecipe:
    source = str(entry.get("source", "")).strip()
    if not source:
        message = (
            "every recipe names its source, because a save region is a claim about a game "
            "and a claim without evidence is a guess"
        )
        raise ValueError(message)

    fill = int(entry.get("fill", 0))
    if not 0 <= fill <= BYTE_MAX:
        message = f"a fill byte is between 0 and 255, got {fill}"
        raise ValueError(message)

    return SaveRecipe(
        game_name=str(entry["game_name"]),
        game_version=int(entry.get("game_version", 0)),
        side=int(entry.get("side", 0)),
        position=int(entry["position"]),
        fill=fill,
    )


def load_recipes(path: Path) -> tuple[SaveRecipe, ...]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    version = int(payload.get("version", 0))
    if version != RECIPE_VERSION:
        message = f"this file declares recipe version {version}, expected {RECIPE_VERSION}"
        raise ValueError(message)

    entries = cast("list[dict[str, Any]]", payload.get("recipes") or [])
    if not entries:
        message = f"{path} holds no recipes"
        raise ValueError(message)

    return tuple(_entry_to_recipe(entry) for entry in entries)


def recipes_for(
    recipes: Sequence[SaveRecipe],
    *,
    game_name: str,
    game_version: int | None = None,
) -> tuple[SaveRecipe, ...]:
    return tuple(
        recipe
        for recipe in recipes
        if recipe.game_name == game_name
        and (game_version is None or recipe.game_version == game_version)
    )
