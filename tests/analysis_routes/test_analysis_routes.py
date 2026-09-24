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


def test_calibrate_measures_the_drive_against_a_known_disk(client: TestClient) -> None:
    body = client.post("/api/calibrate", json={"data": ONE, "reads": [ONE]}).json()

    assert body["rows"]


def test_calibrate_needs_a_read_to_compare(client: TestClient) -> None:
    answer = client.post("/api/calibrate", json={"data": ONE, "reads": []})

    assert answer.status_code == UNPROCESSABLE


def test_integrity_looks_past_the_checksums(client: TestClient) -> None:
    body = client.post("/api/integrity", json={"data": ONE}).json()

    assert isinstance(body["rows"], list)


def test_splice_needs_a_donor(client: TestClient) -> None:
    answer = client.post("/api/splice", json={"data": ONE, "donors": []})

    assert answer.status_code == UNPROCESSABLE


def test_splice_repairs_from_a_donor(client: TestClient) -> None:
    body = client.post("/api/splice", json={"data": ONE, "donors": [ONE]}).json()

    assert body["size"] == len(ONE_SIDE)


def test_consensus_merges_several_dumps(client: TestClient) -> None:
    body = client.post("/api/consensus", json={"images": [ONE, ONE]}).json()

    assert body["size"] == len(ONE_SIDE)


def test_consensus_needs_a_dump(client: TestClient) -> None:
    answer = client.post("/api/consensus", json={"images": []})

    assert answer.status_code == UNPROCESSABLE


def test_masters_builds_one_master_per_game(client: TestClient) -> None:
    body = client.post(
        "/api/masters",
        json={"images": [ONE, ONE], "names": ["a.fds", "b.fds"]},
    ).json()

    assert body["rows"]


def test_masters_needs_a_corpus(client: TestClient) -> None:
    answer = client.post("/api/masters", json={"images": []})

    assert answer.status_code == UNPROCESSABLE


def test_a_reference_set_is_published_and_verified(client: TestClient) -> None:
    built = client.post(
        "/api/reference-build",
        json={"images": [ONE], "names": ["a.fds"], "set_version": "2026-09-23"},
    ).json()

    verified = client.post(
        "/api/reference-verify",
        json={"data": ONE, "reference": built["data"]},
    ).json()

    assert verified["rows"]


def test_a_reference_set_that_does_not_parse_is_refused(client: TestClient) -> None:
    rubbish = base64.b64encode(b"{").decode("ascii")

    answer = client.post("/api/reference-verify", json={"data": ONE, "reference": rubbish})

    assert answer.status_code == BAD_REQUEST


def test_dat_build_emits_a_catalogue(client: TestClient) -> None:
    body = client.post(
        "/api/dat-build",
        json={"images": [ONE], "names": ["a.fds"], "set_version": "1"},
    ).json()

    assert "datafile" in base64.b64decode(body["data"]).decode("utf-8", "replace")


def test_identify_matches_against_a_catalogue(client: TestClient) -> None:
    built = client.post(
        "/api/dat-build",
        json={"images": [ONE], "names": ["a.fds"], "set_version": "1"},
    ).json()

    body = client.post("/api/identify", json={"data": ONE, "dat": built["data"]}).json()

    assert body["rows"]


def test_a_catalogue_that_does_not_parse_is_refused(client: TestClient) -> None:
    rubbish = base64.b64encode(b"<nope").decode("ascii")

    answer = client.post("/api/identify", json={"data": ONE, "dat": rubbish})

    assert answer.status_code == BAD_REQUEST


def test_bios_identifies_a_firmware_image(client: TestClient) -> None:
    payload = base64.b64encode(bytes(8192)).decode("ascii")

    body = client.post("/api/bios", json={"data": payload}).json()

    assert body["rows"]


def test_the_dat_cache_reports_what_it_holds(client: TestClient) -> None:
    body = client.get("/api/dat-cache").json()

    assert isinstance(body["rows"], list)
