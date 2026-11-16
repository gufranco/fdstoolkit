from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest


@pytest.fixture(name="gate")
def gate_fixture() -> Iterator[threading.Event]:
    gate = threading.Event()
    yield gate
    gate.set()
