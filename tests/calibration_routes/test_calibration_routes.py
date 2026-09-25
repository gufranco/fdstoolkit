from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

import pytest
from drive_double import SimulatedDrive
from fastapi.testclient import TestClient

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.calibration import TRUSTED_DRIVE, calibration_disk, calibration_image
from fdstoolkit.codecs import fds
from fdstoolkit.ui.app import create_app

if TYPE_CHECKING:
    from fastapi import FastAPI

OK = 200
UNPROCESSABLE = 422
SETTLE = 5.0
OLD_DISK, _ = fds.decode(blank_image(sides=2, headered=False, formatted=True, game_name="OLD"))


@pytest.fixture(name="app")
def app_fixture() -> FastAPI:
    return create_app()


@pytest.fixture(name="client")
def client_fixture(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture(name="drive")
def drive_fixture(monkeypatch: pytest.MonkeyPatch) -> SimulatedDrive:
    drive = SimulatedDrive(OLD_DISK)
    monkeypatch.setattr("fdstoolkit.ui.hardware_routes.open_fdsstick", lambda: drive)
    return drive


def run(app: FastAPI, client: TestClient, payload: dict[str, object]) -> dict[str, Any]:
    started = client.post("/api/jobs/write", json=payload)
    assert started.status_code == OK, started.text
    job_id = started.json()["id"]
    assert app.state.jobs.wait(job_id, SETTLE)
    finished: dict[str, Any] = client.get(f"/api/jobs/{job_id}").json()
    return finished


def test_blank_offers_the_calibration_image(client: TestClient) -> None:
    body = client.post("/api/blank", json={"calibration": True}).json()

    assert body["name"] == "calibration.fds"
    assert base64.b64decode(body["data"]) == calibration_image(headered=False)


def test_blank_refuses_settings_the_calibration_image_decides(client: TestClient) -> None:
    answer = client.post("/api/blank", json={"calibration": True, "game_name": "ABC"})

    assert answer.status_code == UNPROCESSABLE
    assert "decides its own sides" in answer.json()["detail"]


@pytest.mark.usefixtures("drive")
def test_the_calibration_disk_is_not_written_without_the_trusted_drive_confirmation(
    client: TestClient,
) -> None:
    answer = client.post("/api/jobs/write", json={"calibration": True, "confirm": True})

    detail = answer.json()["detail"]
    assert answer.status_code == UNPROCESSABLE
    assert "trusted drive confirmation" in detail
    assert all(line in detail for line in TRUSTED_DRIVE)


def test_a_confirmed_calibration_write_lists_the_checklist_and_writes_the_disk(
    app: FastAPI, client: TestClient, drive: SimulatedDrive
) -> None:
    job = run(app, client, {"calibration": True, "trusted_drive": True, "confirm": True})

    assert job["state"] == "done", job
    assert job["steps"][: len(TRUSTED_DRIVE)] == list(TRUSTED_DRIVE)
    assert job["result"]["ok"]
    written = drive.disk
    assert written is not None
    assert [[b.payload for b in side.blocks] for side in written.sides] == [
        [b.payload for b in side.blocks] for side in calibration_disk().sides
    ]


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"confirm": True}, "an image or the calibration disk"),
        (
            {"data": "AA==", "calibration": True, "trusted_drive": True, "confirm": True},
            "an image or the calibration disk",
        ),
        ({"data": "AA==", "trusted_drive": True, "confirm": True}, "only applies"),
    ],
)
@pytest.mark.usefixtures("drive")
def test_write_takes_an_image_or_the_calibration_disk(
    client: TestClient, payload: dict[str, object], reason: str
) -> None:
    answer = client.post("/api/jobs/write", json=payload)

    assert answer.status_code == UNPROCESSABLE
    assert reason in answer.json()["detail"]
