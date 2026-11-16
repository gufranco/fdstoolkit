from __future__ import annotations

import base64
import threading
from collections.abc import Iterator
from typing import TYPE_CHECKING, Final

import pytest
from capture_fixture import disk_with_a_file
from drive_double import FaultPlan, SimulatedDrive
from fakes import game_name, seeded
from fastapi.testclient import TestClient
from hardware_routes_kit import SETTLE, run, serve
from json_view import Json

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs import fds
from fdstoolkit.drive.rescue import load_zip
from fdstoolkit.hardware.ports import BlockRead
from fdstoolkit.ui.app import create_app
from fdstoolkit.ui.jobs import JobState

if TYPE_CHECKING:
    from fastapi import FastAPI

FAKE = seeded(__name__)
OTHER_GAME = game_name(FAKE)
DAMAGED: Final = 3
BAD_REQUEST: Final = 400


@pytest.fixture(name="app")
def app_fixture() -> FastAPI:
    return create_app()


@pytest.fixture(name="client")
def client_fixture(app: FastAPI) -> TestClient:
    return TestClient(app, base_url="http://127.0.0.1")


def _zip_of(job: Json) -> bytes:
    return base64.b64decode(str(job["result"]["data"].value))


def test_a_first_rescue_hands_back_its_reads_and_no_image(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    damaged = FaultPlan(bad_crc_blocks=frozenset({DAMAGED}))
    serve(monkeypatch, SimulatedDrive(disk_with_a_file(), plan=damaged))

    # Act
    job = run(app, client, "/api/jobs/rescue", {"passes": 2})

    # Assert
    assert job["state"] == JobState.DONE
    assert job["result"]["settled"].value is False
    assert job["result"]["image"].value is None
    assert job["result"]["name"] == "rescue.zip"
    assert f"side 0: 1 block(s) unsettled after 2 read(s): {DAMAGED}" in job["steps"]
    assert load_zip(_zip_of(job)).reads_of(0) == 2


def test_a_rescue_handed_back_settles_on_a_clean_read_and_offers_the_image(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    disk = disk_with_a_file()
    damaged = FaultPlan(bad_crc_blocks=frozenset({DAMAGED}))
    serve(monkeypatch, SimulatedDrive(disk, plan=damaged))
    first = run(app, client, "/api/jobs/rescue", {"passes": 1})
    serve(monkeypatch, SimulatedDrive(disk))
    kept = base64.b64encode(_zip_of(first)).decode("ascii")

    # Act
    job = run(app, client, "/api/jobs/rescue", {"captures": kept, "passes": 3})

    # Assert
    assert job["result"]["settled"].value is True
    image = base64.b64decode(str(job["result"]["image"]["data"].value))
    written, _ = fds.decode(image)
    assert written.sides[0].blocks[DAMAGED].payload == disk.sides[0].blocks[DAMAGED].payload
    assert load_zip(_zip_of(job)).reads_of(0) == 2


def test_a_rescue_of_another_disk_fails_and_hands_back_what_was_kept(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    damaged = FaultPlan(bad_crc_blocks=frozenset({DAMAGED}))
    serve(monkeypatch, SimulatedDrive(disk_with_a_file(), plan=damaged))
    first = run(app, client, "/api/jobs/rescue", {"passes": 1})
    other, _ = fds.decode(
        blank_image(sides=1, headered=False, formatted=True, game_name=OTHER_GAME)
    )
    serve(monkeypatch, SimulatedDrive(other))
    kept = base64.b64encode(_zip_of(first)).decode("ascii")

    # Act
    job = run(app, client, "/api/jobs/rescue", {"captures": kept})

    # Assert
    assert job["state"] == JobState.FAILED
    assert str(job["error"]).startswith("this rescue is of ")
    assert job["kept"]["name"] == "rescue.zip"
    returned = base64.b64decode(str(job["kept"]["data"].value))
    assert load_zip(returned).reads_of(0) == 1


def test_a_rescue_zip_that_is_not_one_is_refused_before_the_drive_opens(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = serve(monkeypatch, SimulatedDrive(disk_with_a_file()))
    payload = {"captures": base64.b64encode(b"not a zip").decode("ascii")}

    # Act
    answer = client.post("/api/jobs/rescue", json=payload)

    # Assert
    assert answer.status_code == BAD_REQUEST
    assert drive.read_count == 0


class HeldReads(SimulatedDrive):
    def __init__(self, gate: threading.Event) -> None:
        super().__init__(disk_with_a_file(), plan=FaultPlan(bad_crc_blocks=frozenset({DAMAGED})))
        self.gate = gate

    def read_side(self, side: int) -> Iterator[BlockRead]:
        self.gate.wait(SETTLE)
        return super().read_side(side)


def test_a_rescue_stops_between_reads_when_asked(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    gate = threading.Event()
    serve(monkeypatch, HeldReads(gate))
    job_id = client.post("/api/jobs/rescue", json={"passes": 5}).json()["id"]

    # Act
    client.post(f"/api/jobs/{job_id}/stop")

    # Assert
    gate.set()
    assert app.state.jobs.wait(job_id, SETTLE)
    done = Json(client.get(f"/api/jobs/{job_id}").json())
    assert load_zip(_zip_of(done)).reads_of(0) == 1
