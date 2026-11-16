from __future__ import annotations

import base64
from typing import TYPE_CHECKING

import pytest
from drive_double import FacingDrive, FaultPlan, SimulatedDrive

from fdstoolkit.build.blank import blank_image
from fdstoolkit.history.entries import disk_key
from fdstoolkit.history.logbook import logbook_path
from fdstoolkit.ui.jobs import JobState

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
from hardware_routes_kit import (
    CONFLICT,
    OK,
    ONE,
    ONE_SIDE,
    OTHER,
    OTHER_GAME,
    SETTLE,
    TWO_SIDE,
    UNPROCESSABLE,
    FirstWriteHeld,
    disk_of,
    long_image,
    run,
    serve,
)

ONE_SIDE_COUNTED = 1268


def rate_line(read: int) -> str:
    return (
        f"side 0 read {read}: 100.00% of {ONE_SIDE_COUNTED} pulses fit a class, counted from "
        "the first block to the end of the last declared one"
    )


def logged_line() -> str:
    key = disk_key(disk_of(ONE_SIDE))
    assert key is not None
    return f"logged under {key.id} in {logbook_path()}"


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
    # Arrange
    body = dict(payload)

    # Act
    answer = client.post(route, json=body)

    # Assert
    assert answer.status_code == CONFLICT
    assert "no FDSStick is attached" in answer.json()["detail"]


def test_a_dump_job_reads_the_disk_and_closes_the_drive(
    app: FastAPI, client: TestClient, attached: SimulatedDrive
) -> None:
    # Arrange
    expected = JobState.DONE

    # Act
    job = run(app, client, "/api/jobs/dump", {"sides": 1})

    # Assert
    assert job["state"] == expected
    assert job["result"]["grade"] == "clean"
    assert job["steps"] == ["reading side 0", rate_line(1), logged_line()]
    assert attached.closed


@pytest.mark.usefixtures("attached")
def test_a_dump_job_honours_repeated_passes(app: FastAPI, client: TestClient) -> None:
    # Arrange
    expected = JobState.DONE

    # Act
    job = run(app, client, "/api/jobs/dump", {"sides": 1, "passes": 2})

    # Assert
    assert job["state"] == expected
    assert job["steps"] == [
        "reading side 0",
        "reading side 0",
        rate_line(1),
        rate_line(2),
        logged_line(),
    ]


def test_a_two_side_dump_job_waits_for_the_disk_to_be_turned(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = FacingDrive(disk_of(TWO_SIDE))
    serve(monkeypatch, drive)
    job_id = client.post("/api/jobs/dump", json={"sides": 2}).json()["id"]
    reached = app.state.jobs.wait_for_state(job_id, JobState.WAITING, SETTLE)
    waiting = client.get(f"/api/jobs/{job_id}").json()
    drive.turn(waiting["prompt"])

    # Act
    answered = client.post(f"/api/jobs/{job_id}/answer", json={"yes": True})

    # Assert
    assert reached
    assert "turn the disk over" in waiting["prompt"]
    assert answered.status_code == OK
    assert app.state.jobs.wait(job_id, SETTLE)
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == JobState.DONE


def test_a_declined_turn_fails_the_dump_job(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    serve(monkeypatch, FacingDrive(disk_of(TWO_SIDE)))
    job_id = client.post("/api/jobs/dump", json={"sides": 2}).json()["id"]
    app.state.jobs.wait_for_state(job_id, JobState.WAITING, SETTLE)

    # Act
    client.post(f"/api/jobs/{job_id}/answer", json={"yes": False})

    # Assert
    assert app.state.jobs.wait(job_id, SETTLE)
    failed = client.get(f"/api/jobs/{job_id}").json()
    assert failed["state"] == JobState.FAILED
    assert "declined to turn the disk over" in failed["error"]


def test_a_dump_from_a_drive_with_no_disk_fails_the_job(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    serve(monkeypatch, SimulatedDrive(None))

    # Act
    job = run(app, client, "/api/jobs/dump", {"sides": 1})

    # Assert
    assert job["state"] == JobState.FAILED
    assert "no disk" in job["error"]


def test_a_dump_of_more_sides_than_a_disk_has_is_refused(client: TestClient) -> None:
    # Arrange
    route = "/api/jobs/dump"
    payload = {"sides": 4}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE


@pytest.mark.usefixtures("attached")
def test_a_write_job_refuses_a_side_longer_than_any_factory_side(client: TestClient) -> None:
    # Arrange
    route = "/api/jobs/write"
    payload = {"data": long_image(), "confirm": True}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE
    assert "Tick long side to write it anyway" in answer.json()["detail"]


def test_a_write_job_writes_a_long_side_when_told_to(
    app: FastAPI, client: TestClient, attached: SimulatedDrive
) -> None:
    # Arrange
    expected = JobState.DONE

    # Act
    job = run(
        app,
        client,
        "/api/jobs/write",
        {"data": long_image(), "confirm": True, "long_side": True},
    )

    # Assert
    assert job["state"] == expected
    assert attached.write_count == 1


@pytest.mark.usefixtures("attached")
def test_a_write_job_refuses_without_a_confirmation(client: TestClient) -> None:
    # Arrange
    route = "/api/jobs/write"
    payload = {"data": ONE}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE
    assert "confirm" in answer.json()["detail"]


def test_a_confirmed_write_job_verifies_and_returns_the_backup(
    app: FastAPI, client: TestClient, attached: SimulatedDrive
) -> None:
    # Arrange
    expected = JobState.DONE

    # Act
    job = run(app, client, "/api/jobs/write", {"data": ONE, "confirm": True})

    # Assert
    assert job["state"] == expected
    assert job["result"]["headline"] == "the disk reads back as written, on this drive, grade clean"
    assert any("read the disk on a second drive" in step for step in job["steps"])
    assert job["result"]["file"]["name"] == "before.fds"
    assert job["result"]["ok"]
    assert attached.closed


def test_a_two_side_write_job_turns_the_disk_once(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = FacingDrive(disk_of(TWO_SIDE))
    serve(monkeypatch, drive)
    job_id = client.post("/api/jobs/write", json={"data": OTHER, "confirm": True}).json()["id"]
    reached = app.state.jobs.wait_for_state(job_id, JobState.WAITING, SETTLE)
    drive.turn("")

    # Act
    client.post(f"/api/jobs/{job_id}/answer", json={"yes": True})

    # Assert
    assert reached
    assert app.state.jobs.wait(job_id, SETTLE)
    done = client.get(f"/api/jobs/{job_id}").json()
    assert done["state"] == JobState.DONE
    assert done["result"]["ok"]
    assert "writing side 1" in done["steps"]


def test_a_multi_pass_dump_job_keeps_its_unstable_grade_and_names_the_blocks(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    plan = FaultPlan(bad_crc_blocks=frozenset({1}), unstable_blocks=frozenset({0}))
    serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE), plan=plan))

    # Act
    job = run(app, client, "/api/jobs/dump", {"passes": 3, "retries": 0})

    # Assert
    assert job["result"]["grade"] == "unstable"
    assert "side 0: block 0 differs between passes" in job["steps"]


def test_a_write_job_that_fails_still_offers_the_backup(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE), plan=FaultPlan(writes_do_not_stick=True)))

    # Act
    job = run(app, client, "/api/jobs/write", {"data": OTHER, "confirm": True})

    # Assert
    assert job["state"] == JobState.FAILED
    assert job["kept"]["name"] == "before.fds"
    assert base64.b64decode(job["kept"]["data"].text())[:1] == bytes([0x01])


def test_a_surface_job_can_be_stopped_between_patterns(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attached = serve(monkeypatch, FirstWriteHeld(disk_of(ONE_SIDE)))
    started = client.post("/api/jobs/surface", json={"confirm": True, "passes": 3}).json()
    attached.writing.wait(SETTLE)

    # Act
    client.post(f"/api/jobs/{started['id']}/stop", json={})

    # Assert
    attached.release.set()
    assert app.state.jobs.wait(started["id"], SETTLE)
    job = client.get(f"/api/jobs/{started['id']}").json()
    assert started["stoppable"] is True
    assert job["state"] == JobState.DONE
    assert job["result"]["rows"][0]["refusal"] == ""
    assert "interrupted" in job["result"]["headline"]
    assert attached.write_count < 3 * 4


def test_a_write_job_reports_blocks_that_did_not_read_back(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    serve(
        monkeypatch,
        SimulatedDrive(disk_of(ONE_SIDE), plan=FaultPlan(unstable_blocks=frozenset({1}))),
    )

    # Act
    job = run(app, client, "/api/jobs/write", {"data": ONE, "confirm": True})

    # Assert
    assert job["state"] == JobState.DONE
    assert job["result"]["rows"] == [
        {"side": 0, "block": 1, "finding": "did not read back as written"}
    ]
    assert "did not read back as written" in job["result"]["headline"]
    assert not job["result"]["ok"]


def test_a_write_the_disk_does_not_take_fails_the_job(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE), plan=FaultPlan(writes_do_not_stick=True)))
    other = base64.b64encode(
        blank_image(sides=1, headered=False, formatted=True, game_name=OTHER_GAME)
    )

    # Act
    job = run(app, client, "/api/jobs/write", {"data": other.decode("ascii"), "confirm": True})

    # Assert
    assert job["state"] == JobState.FAILED
    assert "did not take the write" in job["error"]
