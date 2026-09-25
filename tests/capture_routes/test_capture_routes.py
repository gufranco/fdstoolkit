from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

import pytest
from capture_fixture import DAMAGED, disk_with_a_file, image_of, zipped
from drive_double import FaultPlan, SimulatedDrive
from fastapi.testclient import TestClient

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs import fds
from fdstoolkit.drive.captures import read_zip
from fdstoolkit.ui.app import create_app

if TYPE_CHECKING:
    from fastapi import FastAPI

OK = 200
UNPROCESSABLE = 422
SETTLE = 5.0
VOTED = (10, 90, 170)
BLANK, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@pytest.fixture(name="app")
def app_fixture() -> FastAPI:
    return create_app()


@pytest.fixture(name="client")
def client_fixture(app: FastAPI) -> TestClient:
    return TestClient(app)


def serve(monkeypatch: pytest.MonkeyPatch, drive: SimulatedDrive) -> SimulatedDrive:
    monkeypatch.setattr("fdstoolkit.ui.hardware_routes.open_fdsstick", lambda: drive)
    return drive


def no_drive(monkeypatch: pytest.MonkeyPatch) -> None:
    def opener() -> SimulatedDrive:
        message = "the drive must not be opened to replay saved captures"
        raise AssertionError(message)

    monkeypatch.setattr("fdstoolkit.ui.hardware_routes.open_fdsstick", opener)


def run(app: FastAPI, client: TestClient, route: str, payload: dict[str, object]) -> dict[str, Any]:
    started = client.post(route, json=payload)
    assert started.status_code == OK, started.text
    job_id = started.json()["id"]
    assert app.state.jobs.wait(job_id, SETTLE)
    finished: dict[str, Any] = client.get(f"/api/jobs/{job_id}").json()
    return finished


def test_a_dump_job_recovers_a_failed_block_like_the_command_line(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(
        monkeypatch,
        SimulatedDrive(BLANK, plan=FaultPlan(bad_crc_blocks=frozenset({1}))),
    )

    job = run(app, client, "/api/jobs/dump", {"retries": 2})

    assert job["state"] == "done", job
    assert "side 0 block 1: recovered by a pulse vote across 3 reads" in job["steps"]
    assert job["result"]["grade"] == "marginal"
    assert job["result"]["captures"] is None


def test_a_dump_job_hands_back_the_captures_it_was_asked_to_keep(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(monkeypatch, SimulatedDrive(disk_with_a_file()))

    job = run(app, client, "/api/jobs/dump", {"keep_captures": True})

    kept = job["result"]["captures"]
    assert kept["name"] == "dump.captures.zip"
    bundle = read_zip(base64.b64decode(kept["data"]))
    assert bundle.image == "dump.fds"
    assert bundle.sides == (0,)


def test_consensus_rebuilds_a_disk_from_uploaded_captures(client: TestClient) -> None:
    disk = disk_with_a_file()

    body = client.post("/api/consensus", json={"captures": b64(zipped(disk, VOTED))}).json()

    rebuilt, _ = fds.decode(base64.b64decode(body["file"]["data"]))
    assert [b.payload for b in rebuilt.sides[0].blocks] == [b.payload for b in disk.sides[0].blocks]
    assert body["ok"]
    assert "1 block(s) recovered by a pulse vote" in body["headline"]


def test_consensus_merges_uploaded_captures_with_a_dump(client: TestClient) -> None:
    disk = disk_with_a_file()

    body = client.post(
        "/api/consensus",
        json={"images": [b64(image_of(disk))], "captures": b64(zipped(disk, VOTED))},
    ).json()

    assert body["ok"]
    assert body["headline"] == "every dump agrees on every block"


def test_consensus_from_captures_names_the_block_it_could_not_fix(client: TestClient) -> None:
    body = client.post(
        "/api/consensus", json={"captures": b64(zipped(disk_with_a_file(), (10,)))}
    ).json()

    assert not body["ok"]
    assert body["rows"] == [{"side": 0, "block": DAMAGED}]


def test_consensus_refuses_captures_that_are_not_a_bundle(client: TestClient) -> None:
    answer = client.post("/api/consensus", json={"captures": b64(b"not a zip")})

    assert answer.status_code == UNPROCESSABLE
    assert "not a zip archive" in answer.json()["detail"]


def test_consensus_of_a_single_dump_is_refused_rather_than_crashing(client: TestClient) -> None:
    answer = client.post("/api/consensus", json={"images": [b64(image_of(disk_with_a_file()))]})

    assert answer.status_code == UNPROCESSABLE
    assert "at least two dumps" in answer.json()["detail"]


def test_reads_maps_weak_blocks_in_uploaded_captures(client: TestClient) -> None:
    body = client.post(
        "/api/reads", json={"captures": b64(zipped(disk_with_a_file(), (None, 10, None)))}
    ).json()

    assert body["reads"] == 3
    assert [(row["side"], row["block"]) for row in body["weak"]] == [(0, DAMAGED)]


def test_grade_counts_weak_blocks_from_uploaded_captures(client: TestClient) -> None:
    disk = disk_with_a_file()

    body = client.post(
        "/api/grade",
        json={"data": b64(image_of(disk)), "captures": b64(zipped(disk, (None, 10, None)))},
    ).json()

    assert body["grade"] == "marginal"
    assert any(reason["metric"] == "weak blocks" for reason in body["reasons"])


def test_calibration_replays_uploaded_captures_without_opening_the_drive(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_drive(monkeypatch)
    disk = disk_with_a_file()

    job = run(
        app,
        client,
        "/api/jobs/calibrate",
        {
            "mode": "head",
            "reference": b64(image_of(disk)),
            "captures": b64(zipped(disk, (10, None))),
        },
    )

    assert job["state"] == "done", job
    assert len(job["result"]["rows"]) == 2
    assert any("console error 27" in line for line in job["steps"])


def test_calibration_refuses_captures_with_no_read_of_that_side(client: TestClient) -> None:
    answer = client.post(
        "/api/jobs/calibrate",
        json={"mode": "speed", "side": 1, "captures": b64(zipped(disk_with_a_file(), (None,)))},
    )

    assert answer.status_code == UNPROCESSABLE
    assert "hold no read of side 1" in answer.json()["detail"]
