from __future__ import annotations

import base64
from pathlib import Path

import pytest
from capture_fixture import DAMAGED, disk_with_a_file, zipped
from fakes import game_name, seeded
from fastapi.testclient import TestClient

from fdstoolkit.build.blank import blank_image
from fdstoolkit.ui.app import create_app

FAKE = seeded(__name__)
GAME = game_name(FAKE)

OK = 200
BAD_REQUEST = 400
UNPROCESSABLE = 422
SERVER_ERROR = 500
ONE_SIDE = blank_image(sides=1, headered=False, formatted=True, game_name=GAME)
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


def test_splice_refuses_a_donor_of_another_shape(client: TestClient) -> None:
    # Arrange
    two = base64.b64encode(
        blank_image(sides=2, headered=False, formatted=True, game_name=GAME)
    ).decode("ascii")

    # Act
    answer = client.post("/api/splice", json={"data": ONE, "donors": [two]})

    # Assert
    assert answer.status_code == UNPROCESSABLE
    assert answer.json()["detail"] == "a donor has a different shape from the image being repaired"


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


def test_a_graded_image_is_logged_and_its_history_shown(client: TestClient) -> None:
    # Arrange
    client.post("/api/grade", json={"data": ONE})
    client.post("/api/grade", json={"data": ONE})

    # Act
    answer = client.post("/api/log", json={"data": ONE})

    # Assert
    assert answer.status_code == OK
    body = answer.json()
    assert [entry["kind"] for entry in body["entries"]] == ["grade", "grade"]
    assert body["headline"] == body["subject"]
    assert body["text"].splitlines()[-1].endswith(", no block changed")


def test_the_log_of_a_drive_with_no_entries_says_so(client: TestClient) -> None:
    # Arrange
    payload = {"drive": "nobody"}

    # Act
    answer = client.post("/api/log", json=payload)

    # Assert
    assert answer.json()["text"] == "nothing is logged for this yet"
    assert answer.json()["subject"] == "drive nobody"


def test_the_log_needs_a_disk_or_a_drive(client: TestClient) -> None:
    # Arrange
    payload: dict[str, object] = {}

    # Act
    answer = client.post("/api/log", json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE
    assert answer.json()["detail"] == "name a disk image or a drive label to show its history"


def test_a_logbook_that_cannot_be_read_is_a_server_fault(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    store = tmp_path / "broken.sqlite3"
    store.write_bytes(b"not a database, only text that sqlite refuses to open " * 64)
    monkeypatch.setenv("FDSTOOLKIT_LOGBOOK", str(store))

    # Act
    answer = client.post("/api/log", json={"drive": "twin"})

    # Assert
    assert answer.status_code == SERVER_ERROR
    assert answer.json()["detail"].startswith(f"could not read the logbook at {store}: ")


def test_a_grade_that_cannot_be_logged_is_a_server_fault(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"")
    monkeypatch.setenv("FDSTOOLKIT_LOGBOOK", str(blocker / "logbook.sqlite3"))

    # Act
    answer = client.post("/api/grade", json={"data": ONE})

    # Assert
    assert answer.status_code == SERVER_ERROR
    assert "could not write the logbook at" in answer.json()["detail"]


def test_the_track_of_uploaded_captures_marks_the_weak_block(client: TestClient) -> None:
    # Arrange
    payload = {"captures": base64.b64encode(zipped(disk_with_a_file(), (None, 10, None))).decode()}

    # Act
    answer = client.post("/api/track", json=payload)

    # Assert
    assert answer.status_code == OK
    body = answer.json()
    assert [block["index"] for block in body["blocks"] if block["weak"]] == [DAMAGED]
    assert body["headline"].endswith(", 1 weak")


def test_the_track_of_a_side_never_read_is_refused(client: TestClient) -> None:
    # Arrange
    payload = {
        "captures": base64.b64encode(zipped(disk_with_a_file(), (None,))).decode(),
        "side": 1,
    }

    # Act
    answer = client.post("/api/track", json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE
    assert answer.json()["detail"] == "the captures hold no read of side 1"
