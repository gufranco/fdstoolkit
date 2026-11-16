from __future__ import annotations

import json

RECIPE_VERSION = 1


def recipe_text(*, game_name: str, source: str) -> str:
    recipe = {
        "game_name": game_name,
        "game_version": 0,
        "side": 0,
        "position": 0,
        "fill": 0,
        "source": source,
    }
    return json.dumps({"version": RECIPE_VERSION, "recipes": [recipe]})
