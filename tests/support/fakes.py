from __future__ import annotations

from string import ascii_uppercase
from typing import Final

from faker import Faker

FAKE_SEED: Final = 1986
GAME_NAME_PATTERN: Final = "???"


def seeded(scope: str) -> Faker:
    generator = Faker()
    generator.seed_instance(f"{FAKE_SEED}:{scope}")
    return generator


def game_name(generator: Faker) -> str:
    return generator.unique.lexify(GAME_NAME_PATTERN, letters=ascii_uppercase)
