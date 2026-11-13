from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from fdstoolkit.build.blank import blank_image
from fdstoolkit.ui.app import create_app

OK = 200
BAD_REQUEST = 400
UNPROCESSABLE = 422
ONE_SIDE = blank_image(sides=1, headered=False, formatted=True, game_name="SMB")
ONE = base64.b64encode(ONE_SIDE).decode("ascii")


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(create_app(), base_url="http://127.0.0.1")


def test_splice_needs_a_donor(client: TestClient) -> None:
    # Arrange
    route = "/api/splice"
    payload: dict[str, object] = {"data": ONE, "donors": []}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE


def test_splice_repairs_from_a_donor(client: TestClient) -> None:
    # Arrange
    expected = len(ONE_SIDE)

    # Act
    body = client.post("/api/splice", json={"data": ONE, "donors": [ONE]}).json()

    # Assert
    assert body["size"] == expected


def test_consensus_needs_a_dump(client: TestClient) -> None:
    # Arrange
    route = "/api/consensus"
    payload: dict[str, object] = {"images": []}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE


def test_consensus_of_one_disk_returns_the_merge_and_its_verdict(client: TestClient) -> None:
    # Arrange
    expected = len(ONE_SIDE)

    # Act
    body = client.post("/api/consensus", json={"images": [ONE, ONE]}).json()

    # Assert
    assert body["file"]["size"] == expected
    assert body["headline"] == "every dump agrees on every block"
    assert body["rows"] == []
    assert body["ok"]


def test_consensus_of_one_disk_names_the_blocks_that_disagree(client: TestClient) -> None:
    # Arrange
    other = bytearray(ONE_SIDE)
    other[0x20] ^= 0xFF
    changed = base64.b64encode(bytes(other)).decode("ascii")

    # Act
    body = client.post("/api/consensus", json={"images": [ONE, changed]}).json()

    # Assert
    assert body["rows"]
    assert "disagree" in body["headline"]
    assert not body["ok"]


def test_consensus_names_a_block_one_dump_missed_without_failing(client: TestClient) -> None:
    # Arrange
    short = bytearray(ONE_SIDE)
    short[56:] = bytes(len(short) - 56)
    missed = base64.b64encode(bytes(short)).decode("ascii")

    # Act
    body = client.post("/api/consensus", json={"images": [ONE, missed, ONE]}).json()

    # Assert
    assert body["rows"] == [{"side": 0, "block": 1, "finding": "missing from 1 dump(s)"}]
    assert body["headline"] == "every dump agrees on every block"
    assert body["ok"]


def test_consensus_across_an_empty_corpus_is_refused(client: TestClient) -> None:
    # Arrange
    route = "/api/consensus"
    payload: dict[str, object] = {"images": [], "across": "corpus"}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE
