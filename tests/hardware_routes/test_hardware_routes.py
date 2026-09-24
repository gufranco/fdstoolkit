from __future__ import annotations

import base64
import threading
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import pytest
from drive_double import FacingDrive, FaultPlan, SimulatedDrive
from fastapi.testclient import TestClient

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.disk import Disk
from fdstoolkit.hardware.ports import BlockRead, FaultKind, HardwareFaultError
from fdstoolkit.ui.app import create_app
from fdstoolkit.ui.jobs import JobBoard, JobBusyError, JobState

if TYPE_CHECKING:
    from fastapi import FastAPI

OK = 200
BAD_REQUEST = 400
NOT_FOUND = 404
CONFLICT = 409
UNPROCESSABLE = 422
SETTLE = 5.0
ONE_SIDE = blank_image(sides=1, headered=False, formatted=True, game_name="SMB")
TWO_SIDE = blank_image(sides=2, headered=False, formatted=True, game_name="SMB")
OTHER_TWO = blank_image(sides=2, headered=False, formatted=True, game_name="ZEL")
ONE = base64.b64encode(ONE_SIDE).decode("ascii")
TWO = base64.b64encode(TWO_SIDE).decode("ascii")
OTHER = base64.b64encode(OTHER_TWO).decode("ascii")


def disk_of(image: bytes) -> Disk:
    disk, _ = decode(image)
    return disk


@pytest.fixture(name="app")
def app_fixture() -> FastAPI:
    return create_app()


@pytest.fixture(name="client")
def client_fixture(app: FastAPI) -> TestClient:
    return TestClient(app)


def serve(monkeypatch: pytest.MonkeyPatch, drive: SimulatedDrive) -> SimulatedDrive:
    monkeypatch.setattr("fdstoolkit.ui.hardware_routes.open_fdsstick", lambda: drive)
    return drive


@pytest.fixture(name="attached")
def attached_fixture(monkeypatch: pytest.MonkeyPatch) -> SimulatedDrive:
    return serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE)))


@pytest.fixture(name="absent")
def absent_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    def opener() -> SimulatedDrive:
        message = "no FDSStick is attached"
        raise HardwareFaultError(message, kind=FaultKind.LINK)

    monkeypatch.setattr("fdstoolkit.ui.hardware_routes.open_fdsstick", opener)


def run(app: FastAPI, client: TestClient, route: str, payload: dict[str, object]) -> dict[str, Any]:
    started = client.post(route, json=payload)
    assert started.status_code == OK, started.text
    job_id = started.json()["id"]
    assert app.state.jobs.wait(job_id, SETTLE)
    finished: dict[str, Any] = client.get(f"/api/jobs/{job_id}").json()
    return finished


@pytest.mark.usefixtures("absent")
@pytest.mark.parametrize(
    ("route", "payload"),
    [
        ("/api/jobs/dump", {"sides": 1}),
        ("/api/jobs/write", {"data": ONE, "confirm": True}),
        ("/api/jobs/surface", {"sides": 1, "quick": True, "confirm": True}),
    ],
)
def test_a_disk_job_refuses_when_no_stick_is_attached(
    client: TestClient, route: str, payload: dict[str, object]
) -> None:
    answer = client.post(route, json=payload)

    assert answer.status_code == CONFLICT
    assert "no FDSStick is attached" in answer.json()["detail"]


def test_a_dump_job_reads_the_disk_and_closes_the_drive(
    app: FastAPI, client: TestClient, attached: SimulatedDrive
) -> None:
    job = run(app, client, "/api/jobs/dump", {"sides": 1})

    assert job["state"] == JobState.DONE
    assert job["result"]["grade"] == "clean"
    assert job["steps"] == ["reading side 0"]
    assert attached.closed


@pytest.mark.usefixtures("attached")
def test_a_dump_job_honours_repeated_passes(app: FastAPI, client: TestClient) -> None:
    job = run(app, client, "/api/jobs/dump", {"sides": 1, "passes": 2})

    assert job["state"] == JobState.DONE
    assert job["steps"] == ["reading side 0", "reading side 0"]


def test_a_two_side_dump_job_waits_for_the_disk_to_be_turned(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    drive = FacingDrive(disk_of(TWO_SIDE))
    serve(monkeypatch, drive)

    job_id = client.post("/api/jobs/dump", json={"sides": 2}).json()["id"]
    assert app.state.jobs.wait_for_state(job_id, JobState.WAITING, SETTLE)
    waiting = client.get(f"/api/jobs/{job_id}").json()
    drive.turn(waiting["prompt"])
    answered = client.post(f"/api/jobs/{job_id}/answer", json={"yes": True})

    assert "turn the disk over" in waiting["prompt"]
    assert answered.status_code == OK
    assert app.state.jobs.wait(job_id, SETTLE)
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == JobState.DONE


def test_a_declined_turn_fails_the_dump_job(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(monkeypatch, FacingDrive(disk_of(TWO_SIDE)))

    job_id = client.post("/api/jobs/dump", json={"sides": 2}).json()["id"]
    app.state.jobs.wait_for_state(job_id, JobState.WAITING, SETTLE)
    client.post(f"/api/jobs/{job_id}/answer", json={"yes": False})

    assert app.state.jobs.wait(job_id, SETTLE)
    failed = client.get(f"/api/jobs/{job_id}").json()
    assert failed["state"] == JobState.FAILED
    assert "declined to turn the disk over" in failed["error"]


def test_a_dump_from_a_drive_with_no_disk_fails_the_job(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(monkeypatch, SimulatedDrive(None))

    job = run(app, client, "/api/jobs/dump", {"sides": 1})

    assert job["state"] == JobState.FAILED
    assert "no disk" in job["error"]


def test_a_dump_of_more_sides_than_a_disk_has_is_refused(client: TestClient) -> None:
    answer = client.post("/api/jobs/dump", json={"sides": 4})

    assert answer.status_code == UNPROCESSABLE


@pytest.mark.usefixtures("attached")
def test_a_write_job_refuses_without_a_confirmation(client: TestClient) -> None:
    answer = client.post("/api/jobs/write", json={"data": ONE})

    assert answer.status_code == UNPROCESSABLE
    assert "confirm" in answer.json()["detail"]


def test_a_confirmed_write_job_verifies_and_returns_the_backup(
    app: FastAPI, client: TestClient, attached: SimulatedDrive
) -> None:
    job = run(app, client, "/api/jobs/write", {"data": ONE, "confirm": True})

    assert job["state"] == JobState.DONE
    assert job["result"]["headline"] == "the disk reads back as written, on this drive"
    assert job["result"]["file"]["name"] == "before.fds"
    assert job["result"]["ok"]
    assert attached.closed


def test_a_two_side_write_job_turns_the_disk_once(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    drive = FacingDrive(disk_of(TWO_SIDE))
    serve(monkeypatch, drive)

    job_id = client.post("/api/jobs/write", json={"data": OTHER, "confirm": True}).json()["id"]
    assert app.state.jobs.wait_for_state(job_id, JobState.WAITING, SETTLE)
    drive.turn("")
    client.post(f"/api/jobs/{job_id}/answer", json={"yes": True})

    assert app.state.jobs.wait(job_id, SETTLE)
    done = client.get(f"/api/jobs/{job_id}").json()
    assert done["state"] == JobState.DONE
    assert done["result"]["ok"]
    assert "writing side 1" in done["steps"]


def test_a_write_job_reports_blocks_that_did_not_read_back(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(
        monkeypatch,
        SimulatedDrive(disk_of(ONE_SIDE), plan=FaultPlan(unstable_blocks=frozenset({1}))),
    )

    job = run(app, client, "/api/jobs/write", {"data": ONE, "confirm": True})

    assert job["state"] == JobState.DONE
    assert job["result"]["rows"] == [{"side": 0, "block": 1}]
    assert "did not read back as written" in job["result"]["headline"]
    assert not job["result"]["ok"]


def test_a_write_the_disk_does_not_take_fails_the_job(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE), plan=FaultPlan(writes_do_not_stick=True)))
    other = base64.b64encode(blank_image(sides=1, headered=False, formatted=True, game_name="ZEL"))

    job = run(app, client, "/api/jobs/write", {"data": other.decode("ascii"), "confirm": True})

    assert job["state"] == JobState.FAILED
    assert "did not take the write" in job["error"]


@pytest.mark.usefixtures("attached")
def test_a_surface_job_refuses_without_a_confirmation(client: TestClient) -> None:
    answer = client.post("/api/jobs/surface", json={"sides": 1})

    assert answer.status_code == UNPROCESSABLE


@pytest.mark.usefixtures("attached")
def test_a_confirmed_surface_job_reports_its_coverage(app: FastAPI, client: TestClient) -> None:
    job = run(app, client, "/api/jobs/surface", {"sides": 1, "quick": True, "confirm": True})

    assert job["state"] == JobState.DONE
    assert job["result"]["rows"][0]["coverage"] > 0
    assert job["result"]["headline"] == "grade clean"
    assert "side 0 pass 1 pattern 0x00" in job["steps"]


@pytest.mark.usefixtures("attached")
def test_a_surface_job_can_leave_the_disk_blank(app: FastAPI, client: TestClient) -> None:
    job = run(
        app,
        client,
        "/api/jobs/surface",
        {"sides": 1, "quick": True, "confirm": True, "finish": "blank"},
    )

    assert job["result"]["rows"][0]["finish_verified"]


def test_a_surface_job_names_why_it_stopped(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(
        monkeypatch,
        SimulatedDrive(disk_of(ONE_SIDE), plan=FaultPlan(unstable_blocks=frozenset({1}))),
    )

    job = run(app, client, "/api/jobs/surface", {"sides": 1, "quick": True, "confirm": True})

    assert job["result"]["headline"].startswith("stopped early: a block failed on two patterns")
    assert not job["result"]["ok"]


@pytest.mark.usefixtures("attached")
def test_an_unknown_finish_is_refused(client: TestClient) -> None:
    answer = client.post("/api/jobs/surface", json={"confirm": True, "finish": "nonsense"})

    assert answer.status_code == BAD_REQUEST


@pytest.fixture(name="held")
def held_fixture(monkeypatch: pytest.MonkeyPatch) -> Iterator[threading.Event]:
    gate = threading.Event()

    class HeldDrive(SimulatedDrive):
        def read_side(self, side: int) -> Iterator[BlockRead]:
            gate.wait(SETTLE)
            return super().read_side(side)

    serve(monkeypatch, HeldDrive(disk_of(ONE_SIDE)))
    yield gate
    gate.set()


def test_a_second_disk_job_while_one_runs_is_refused(
    app: FastAPI, client: TestClient, held: threading.Event
) -> None:
    first = client.post("/api/jobs/dump", json={"sides": 1}).json()

    answer = client.post("/api/jobs/dump", json={"sides": 1})

    assert answer.status_code == CONFLICT
    assert "dump is already running" in answer.json()["detail"]
    held.set()
    assert app.state.jobs.wait(first["id"], SETTLE)


def test_the_running_job_is_reported_as_current(
    app: FastAPI, client: TestClient, held: threading.Event
) -> None:
    first = client.post("/api/jobs/dump", json={"sides": 1}).json()

    current = client.get("/api/jobs/current").json()

    assert current["job"]["id"] == first["id"]
    held.set()
    assert app.state.jobs.wait(first["id"], SETTLE)
    assert client.get("/api/jobs/current").json() == {"job": None}


def test_a_job_that_loses_the_race_for_the_drive_closes_it(
    client: TestClient, attached: SimulatedDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    def busy(*args: object, **kwargs: object) -> None:
        del args, kwargs
        message = "write is already running, so the drive is busy"
        raise JobBusyError(message)

    monkeypatch.setattr(JobBoard, "start", busy)

    answer = client.post("/api/jobs/dump", json={"sides": 1})

    assert answer.status_code == CONFLICT
    assert attached.closed


@pytest.mark.usefixtures("attached")
def test_answering_a_job_that_is_not_waiting_is_refused(app: FastAPI, client: TestClient) -> None:
    job = run(app, client, "/api/jobs/dump", {"sides": 1})

    answer = client.post(f"/api/jobs/{job['id']}/answer", json={"yes": True})

    assert answer.status_code == CONFLICT


def test_an_unknown_job_is_not_found(client: TestClient) -> None:
    answer = client.get("/api/jobs/nothing")

    assert answer.status_code == NOT_FOUND
