from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from fdstoolkit.ui.app import create_app

OK = 200
BAD_HOST = 400
FORBIDDEN = 403
LOCAL = "http://127.0.0.1:8000"


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(create_app(), base_url=LOCAL)


def test_a_request_naming_a_foreign_host_is_refused(client: TestClient) -> None:
    answer = client.get("/", headers={"host": "evil.example"})

    assert answer.status_code == BAD_HOST
    assert "evil.example" in answer.json()["detail"]


def test_a_loopback_name_is_accepted_on_any_port(client: TestClient) -> None:
    answers = [
        client.get("/api/catalogue", headers={"host": host})
        for host in ("127.0.0.1:9000", "localhost:8000", "[::1]:8000")
    ]

    assert [answer.status_code for answer in answers] == [OK, OK, OK]


def test_a_published_host_is_accepted_when_the_server_was_bound_to_it() -> None:
    client = TestClient(create_app(allowed_hosts=frozenset({"192.0.2.10"})), base_url=LOCAL)

    answer = client.get("/api/catalogue", headers={"host": "192.0.2.10:8000"})

    assert answer.status_code == OK


def test_a_write_from_another_origin_is_refused(client: TestClient) -> None:
    answer = client.post(
        "/api/blank", headers={"origin": "https://evil.example"}, json={"sides": 1}
    )

    assert answer.status_code == FORBIDDEN
    assert "https://evil.example" in answer.json()["detail"]


def test_a_write_the_browser_marks_cross_site_is_refused(client: TestClient) -> None:
    answer = client.post("/api/blank", headers={"sec-fetch-site": "cross-site"}, json={"sides": 1})

    assert answer.status_code == FORBIDDEN


def test_a_write_from_the_page_itself_is_accepted(client: TestClient) -> None:
    answer = client.post(
        "/api/blank",
        headers={"origin": LOCAL, "sec-fetch-site": "same-origin"},
        json={"sides": 1},
    )

    assert answer.status_code == OK


def test_every_answer_carries_the_protective_headers(client: TestClient) -> None:
    answer = client.get("/api/catalogue")

    assert answer.headers["x-content-type-options"] == "nosniff"
    assert answer.headers["x-frame-options"] == "DENY"
    assert answer.headers["referrer-policy"] == "no-referrer"
    assert answer.headers["cross-origin-opener-policy"] == "same-origin"


def test_the_page_runs_only_the_script_it_was_sent_with(client: TestClient) -> None:
    answer = client.get("/")

    policy = answer.headers["content-security-policy"]
    nonce = re.search(r"'nonce-([^']+)'", policy)
    assert nonce is not None
    assert f'<script type="module" nonce="{nonce.group(1)}">' in answer.text
    assert "'unsafe-inline'" not in policy
    assert "frame-ancestors 'none'" in policy


def test_each_page_load_gets_a_fresh_nonce(client: TestClient) -> None:
    policies = {client.get("/").headers["content-security-policy"] for _ in range(3)}

    assert len(policies) == 3


def test_the_api_documentation_is_not_served(client: TestClient) -> None:
    answer = client.get("/docs")

    assert answer.status_code == 404
