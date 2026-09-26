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
    return TestClient(create_app())


def test_splice_needs_a_donor(client: TestClient) -> None:
    answer = client.post("/api/splice", json={"data": ONE, "donors": []})

    assert answer.status_code == UNPROCESSABLE


def test_splice_repairs_from_a_donor(client: TestClient) -> None:
    body = client.post("/api/splice", json={"data": ONE, "donors": [ONE]}).json()

    assert body["size"] == len(ONE_SIDE)


def test_consensus_needs_a_dump(client: TestClient) -> None:
    answer = client.post("/api/consensus", json={"images": []})

    assert answer.status_code == UNPROCESSABLE


def test_consensus_of_one_disk_returns_the_merge_and_its_verdict(client: TestClient) -> None:
    body = client.post("/api/consensus", json={"images": [ONE, ONE]}).json()

    assert body["file"]["size"] == len(ONE_SIDE)
    assert body["headline"] == "every dump agrees on every block"
    assert body["rows"] == []
    assert body["ok"]


def test_consensus_of_one_disk_names_the_blocks_that_disagree(client: TestClient) -> None:
    other = bytearray(ONE_SIDE)
    other[0x20] ^= 0xFF
    changed = base64.b64encode(bytes(other)).decode("ascii")

    body = client.post("/api/consensus", json={"images": [ONE, changed]}).json()

    assert body["rows"]
    assert "disagree" in body["headline"]
    assert not body["ok"]


def test_consensus_names_a_block_one_dump_missed_without_failing(client: TestClient) -> None:
    short = bytearray(ONE_SIDE)
    short[56:] = bytes(len(short) - 56)
    missed = base64.b64encode(bytes(short)).decode("ascii")

    body = client.post("/api/consensus", json={"images": [ONE, missed, ONE]}).json()

    assert body["rows"] == [{"side": 0, "block": 1, "finding": "missing from 1 dump(s)"}]
    assert body["headline"] == "every dump agrees on every block"
    assert body["ok"]


def test_consensus_across_an_empty_corpus_is_refused(client: TestClient) -> None:
    answer = client.post("/api/consensus", json={"images": [], "across": "corpus"})

    assert answer.status_code == UNPROCESSABLE
