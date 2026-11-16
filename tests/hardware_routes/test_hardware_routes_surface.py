from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest
from drive_double import FaultPlan, SimulatedDrive
from fastapi.testclient import TestClient

from fdstoolkit.ui.jobs import Controls, JobState

if TYPE_CHECKING:
    from fastapi import FastAPI
from hardware_routes_kit import (
    BAD_REQUEST,
    CONFLICT,
    NOT_FOUND,
    OK,
    ONE,
    ONE_SIDE,
    SETTLE,
    TWO_SIDE,
    UNPROCESSABLE,
    Nothing,
    SlowReads,
    disk_of,
    run,
    serve,
)


@pytest.mark.usefixtures("attached")
def test_a_surface_job_refuses_without_a_confirmation(client: TestClient) -> None:
    # Arrange
    route = "/api/jobs/surface"
    payload = {"sides": 1}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE


@pytest.mark.usefixtures("attached")
def test_a_confirmed_surface_job_reports_its_coverage(app: FastAPI, client: TestClient) -> None:
    # Arrange
    expected = JobState.DONE

    # Act
    job = run(app, client, "/api/jobs/surface", {"sides": 1, "quick": True, "confirm": True})

    # Assert
    assert job["state"] == expected
    assert job["result"]["rows"][0]["coverage"].number() > 0
    assert job["result"]["headline"] == "grade clean"
    assert "side 0 pass 1 pattern unique data" in job["steps"]
    assert job["result"]["rows"][0]["pulses"].value is None


@pytest.mark.usefixtures("attached")
def test_a_surface_job_can_leave_the_disk_blank(app: FastAPI, client: TestClient) -> None:
    # Arrange
    payload: dict[str, object] = {"sides": 1, "quick": True, "confirm": True, "finish": "blank"}

    # Act
    job = run(app, client, "/api/jobs/surface", payload)

    # Assert
    assert job["result"]["rows"][0]["finish_verified"]


def test_a_surface_job_names_why_it_stopped(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    serve(
        monkeypatch,
        SimulatedDrive(disk_of(ONE_SIDE), plan=FaultPlan(unstable_blocks=frozenset({1}))),
    )

    # Act
    job = run(app, client, "/api/jobs/surface", {"sides": 1, "quick": True, "confirm": True})

    # Assert
    assert (
        job["result"]["headline"].text().startswith("stopped early: a block failed on two patterns")
    )
    assert not job["result"]["ok"]


@pytest.mark.usefixtures("attached")
def test_an_unknown_finish_is_refused(client: TestClient) -> None:
    # Arrange
    route = "/api/jobs/surface"
    payload = {"confirm": True, "finish": "nonsense"}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == BAD_REQUEST


def test_a_second_disk_job_while_one_runs_is_refused(
    app: FastAPI, client: TestClient, held: threading.Event
) -> None:
    # Arrange
    first = client.post("/api/jobs/dump", json={"sides": 1}).json()

    # Act
    answer = client.post("/api/jobs/dump", json={"sides": 1})

    # Assert
    assert answer.status_code == CONFLICT
    assert "dump is already running" in answer.json()["detail"]
    held.set()
    assert app.state.jobs.wait(first["id"], SETTLE)


def test_the_running_job_is_reported_as_current(
    app: FastAPI, client: TestClient, held: threading.Event
) -> None:
    # Arrange
    first = client.post("/api/jobs/dump", json={"sides": 1}).json()

    # Act
    current = client.get("/api/jobs/current").json()

    # Assert
    assert current["job"]["id"] == first["id"]
    held.set()
    assert app.state.jobs.wait(first["id"], SETTLE)
    assert client.get("/api/jobs/current").json() == {"job": None}


def test_a_job_whose_thread_cannot_start_closes_the_drive(
    app: FastAPI, attached: SimulatedDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    real_start = threading.Thread.start

    def refuse_job_threads(self: threading.Thread) -> None:
        if self.name.startswith("fdstoolkit-"):
            message = "can't start new thread"
            raise RuntimeError(message)
        real_start(self)

    monkeypatch.setattr(threading.Thread, "start", refuse_job_threads)
    client = TestClient(app, raise_server_exceptions=False, base_url="http://127.0.0.1")

    # Act
    answer = client.post("/api/jobs/dump", json={"sides": 1})

    # Assert
    assert answer.status_code == 500
    assert attached.closed


def test_a_job_that_loses_the_race_for_the_drive_closes_it(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = SimulatedDrive(disk_of(ONE_SIDE))
    release = threading.Event()

    def racer(controls: Controls) -> Nothing:
        del controls
        release.wait(SETTLE)
        return Nothing()

    def opened_while_another_job_starts() -> SimulatedDrive:
        app.state.jobs.start("write", writes=True, work=racer)
        return drive

    monkeypatch.setattr(
        "fdstoolkit.ui.hardware_routes.open_fdsstick", opened_while_another_job_starts
    )
    answer = client.post("/api/jobs/dump", json={"sides": 1})

    # Act
    release.set()

    # Assert
    assert answer.status_code == CONFLICT
    assert drive.closed


@pytest.mark.usefixtures("attached")
def test_answering_a_job_that_is_not_waiting_is_refused(app: FastAPI, client: TestClient) -> None:
    # Arrange
    job = run(app, client, "/api/jobs/dump", {"sides": 1})

    # Act
    answer = client.post(f"/api/jobs/{job['id']}/answer", json={"yes": True})

    # Assert
    assert answer.status_code == CONFLICT


def test_an_unknown_job_is_not_found(client: TestClient) -> None:
    # Arrange
    route = "/api/jobs/nothing"

    # Act
    answer = client.get(route)

    # Assert
    assert answer.status_code == NOT_FOUND


@pytest.mark.usefixtures("attached")
def test_a_calibration_against_its_reference_reads_clean(app: FastAPI, client: TestClient) -> None:
    # Arrange
    expected = "done"

    # Act
    job = run(app, client, "/api/jobs/calibrate", {"mode": "speed", "reference": ONE, "passes": 2})

    # Assert
    assert job["state"] == expected
    assert job["stoppable"]
    assert job["steps"][0].text().startswith("judge the drive only with a disk it did not write")
    assert job["steps"][1].text().startswith("read 1: 2 of 2 blocks")
    assert job["result"]["ok"].value is True
    assert job["result"]["mode"] == "speed"
    assert len(job["result"]["rows"]) == 2


@pytest.mark.usefixtures("attached")
def test_a_calibration_without_a_reference_reads_by_checksum(
    app: FastAPI, client: TestClient
) -> None:
    # Arrange
    expected = True

    # Act
    job = run(app, client, "/api/jobs/calibrate", {"mode": "head", "passes": 1})

    # Assert
    assert job["result"]["ok"].value is expected
    assert "pulses short" not in job["steps"][1]


@pytest.mark.usefixtures("attached")
def test_a_calibration_mode_it_does_not_know_is_refused(client: TestClient) -> None:
    # Arrange
    route = "/api/jobs/calibrate"
    payload = {"mode": "belt"}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == BAD_REQUEST


@pytest.mark.usefixtures("attached")
def test_a_reference_side_it_lacks_is_refused(client: TestClient) -> None:
    # Arrange
    route = "/api/jobs/calibrate"
    payload = {"reference": ONE, "side": 1}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE
    assert "has 1 side(s), so it has no side 1" in answer.json()["detail"]


def test_a_calibration_stops_between_reads_when_asked(
    monkeypatch: pytest.MonkeyPatch, app: FastAPI, client: TestClient
) -> None:
    # Arrange
    gate = threading.Event()
    serve(monkeypatch, SlowReads(disk_of(ONE_SIDE), gate))
    job_id = client.post("/api/jobs/calibrate", json={"passes": 50}).json()["id"]

    # Act
    stopping = client.post(f"/api/jobs/{job_id}/stop")

    # Assert
    gate.set()
    assert stopping.status_code == OK
    assert stopping.json()["stopping"] is True
    assert app.state.jobs.wait(job_id, SETTLE)
    done = client.get(f"/api/jobs/{job_id}").json()
    assert len(done["result"]["rows"]) == 1


def test_a_job_that_cannot_stop_refuses_the_stop(
    monkeypatch: pytest.MonkeyPatch, app: FastAPI, client: TestClient
) -> None:
    # Arrange
    serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE)))
    job = run(app, client, "/api/jobs/dump", {"sides": 1})

    # Act
    answer = client.post(f"/api/jobs/{job['id']}/stop")

    # Assert
    assert answer.status_code == CONFLICT


@pytest.mark.usefixtures("attached")
def test_a_bracketed_calibration_waits_for_each_step(app: FastAPI, client: TestClient) -> None:
    # Arrange
    job_id = client.post(
        "/api/jobs/calibrate", json={"reference": ONE, "passes": 2, "bracket": True}
    ).json()["id"]
    reached = app.state.jobs.wait_for_state(job_id, JobState.WAITING, SETTLE)
    waiting = client.get(f"/api/jobs/{job_id}").json()

    # Act
    client.post(f"/api/jobs/{job_id}/answer", json={"yes": True})

    # Assert
    assert reached
    assert "one small step" in waiting["prompt"]
    assert app.state.jobs.wait(job_id, SETTLE)
    assert len(client.get(f"/api/jobs/{job_id}").json()["result"]["rows"]) == 2


def test_a_calibration_job_on_a_stick_that_sends_counts_shows_the_timing(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE), sends_counts=True))

    # Act
    job = run(app, client, "/api/jobs/calibrate", {"mode": "speed", "passes": 1})

    # Assert
    assert any(step.text().startswith("timing: short") for step in job["steps"])
    assert job["result"]["ok"].value is True
    assert len(job["result"]["timing"]) == 1


@pytest.mark.usefixtures("attached")
def test_a_dump_job_can_save_a_qd(app: FastAPI, client: TestClient) -> None:
    # Arrange
    expected = "dump.qd"

    # Act
    job = run(app, client, "/api/jobs/dump", {"qd": True})

    # Assert
    assert job["result"]["name"] == expected
    assert job["result"]["size"].number() % 65536 == 0


def test_a_dump_job_that_fails_still_offers_its_captures(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    class LostAndSkipping(SimulatedDrive):
        @property
        def resyncs(self) -> tuple[tuple[int, int], ...]:
            return ((5, 6),)

    serve(monkeypatch, LostAndSkipping(disk_of(TWO_SIDE), plan=FaultPlan(link_lost_after=1)))

    # Act
    job = run(app, client, "/api/jobs/dump", {"keep_captures": True})

    # Assert
    assert job["state"] == JobState.FAILED
    assert job["kept"]["name"].text().endswith(".zip")
    assert any("the USB link skipped 1 packet(s)" in step for step in job["steps"])


def test_a_dump_job_says_when_the_usb_link_skipped_packets(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    class Skipping(SimulatedDrive):
        @property
        def resyncs(self) -> tuple[tuple[int, int], ...]:
            return ((5, 6),)

    serve(monkeypatch, Skipping(disk_of(ONE_SIDE)))

    # Act
    job = run(app, client, "/api/jobs/dump", {})

    # Assert
    assert any("the USB link skipped 1 packet(s)" in step for step in job["steps"])


def test_a_dump_job_names_a_gap_the_ram_adapter_would_skip(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE), plan=FaultPlan(short_gap_before=1)))

    # Act
    job = run(app, client, "/api/jobs/dump", {})

    # Assert
    assert any(step.text().startswith("side 0: [FDS017] ") for step in job["steps"])


@pytest.mark.usefixtures("attached")
def test_a_calibration_job_reports_the_spread_of_its_reads(
    app: FastAPI, client: TestClient
) -> None:
    # Arrange
    expected = {"reads clean": 2}

    # Act
    job = run(app, client, "/api/jobs/calibrate", {"mode": "speed", "reference": ONE, "passes": 2})

    # Assert
    assert job["result"]["spread"] == expected
    assert job["result"]["timing"] == []
