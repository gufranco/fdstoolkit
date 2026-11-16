from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fdstoolkit.ui.app import (
    create_app,
)


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(create_app(), base_url="http://127.0.0.1")
