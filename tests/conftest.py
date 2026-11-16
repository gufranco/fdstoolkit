from __future__ import annotations

import sys
from pathlib import Path

import pytest
from faker import Faker
from fakes import FAKE_SEED
from hypothesis import settings

settings.register_profile("fixed", derandomize=True, database=None)
settings.load_profile("fixed")


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
def isolated_logbook(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    root: Path = tmp_path_factory.mktemp("logbook")
    monkeypatch.setenv("FDSTOOLKIT_LOGBOOK", str(root / "logbook.sqlite3"))
    monkeypatch.delenv("FDSTOOLKIT_DRIVE", raising=False)


@pytest.fixture(autouse=True)
def hid_out_of_reach(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("hardware") is None:
        monkeypatch.setitem(sys.modules, "hid", None)
