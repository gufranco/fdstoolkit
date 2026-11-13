from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from fdstoolkit.build.fields import FieldError, mapping, number, objects, text
from fdstoolkit.core.disk import SIDES_PER_DISK
from fdstoolkit.edit.saves import SaveRecipe

RECIPE_VERSION: Final = 1


def _entry_to_recipe(entry: Mapping[str, object], index: int) -> SaveRecipe:
    where = f"recipe {index}"
    source = entry.get("source", "")
    if not isinstance(source, str) or not source.strip():
        message = (
            "every recipe names its source, because a save region is a claim about a game "
            "and a claim without evidence is a guess"
        )
        raise FieldError(message)
    return SaveRecipe(
        game_name=text(entry, "game_name", where=where),
        game_version=number(entry, "game_version", where=where, default=0),
        side=number(entry, "side", where=where, default=0, limit=SIDES_PER_DISK - 1),
        position=number(entry, "position", where=where),
        fill=number(entry, "fill", where=where, default=0),
    )


def load_recipes(path: Path) -> tuple[SaveRecipe, ...]:
    payload = mapping(json.loads(path.read_text(encoding="utf-8")), where=str(path))
    version = payload.get("version", 0)
    if version != RECIPE_VERSION:
        message = f"this file declares recipe version {version}, expected {RECIPE_VERSION}"
        raise FieldError(message)
    entries = objects(payload, "recipes", where=str(path))
    if not entries:
        message = f"{path} holds no recipes"
        raise FieldError(message)
    return tuple(_entry_to_recipe(entry, index) for index, entry in enumerate(entries, start=1))


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
