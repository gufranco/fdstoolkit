from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from page_kit import built_page

from fdstoolkit.ui.app import (
    create_app,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(name="client")
def client_fixture(tmp_path: Path) -> TestClient:
    return TestClient(create_app(page_dir=built_page(tmp_path)), base_url="http://127.0.0.1")
