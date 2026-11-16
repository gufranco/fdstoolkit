from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

import pytest
from faker import Faker
from hypothesis import settings

settings.register_profile("fixed", derandomize=True, database=None)
settings.load_profile("fixed")

FAKE_SEED: Final = 1986


@pytest.fixture
def fake() -> Faker:
    generator = Faker()
    generator.seed_instance(FAKE_SEED)
    return generator


@pytest.fixture(autouse=True)
def isolated_cache(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    root: Path = tmp_path_factory.mktemp("cache")
    monkeypatch.setenv("XDG_CACHE_HOME", str(root))


@pytest.fixture(autouse=True)
def hid_out_of_reach(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("hardware") is None:
        monkeypatch.setitem(sys.modules, "hid", None)
