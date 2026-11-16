from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from drive_double import FaultPlan, SimulatedDrive
from hardware_routes_kit import ONE, ONE_SIDE, disk_of, run, serve

from fdstoolkit.history.entries import DRIVE_ENV
from fdstoolkit.history.logbook import LOGBOOK_ENV, EntryKind, history, logbook_path
from fdstoolkit.ui.jobs import JobState

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

BAD_REQUEST = 400


@pytest.mark.usefixtures("attached")
def test_a_first_session_check_logs_a_baseline(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setenv(DRIVE_ENV, "hvc-022")

    # Act
    job = run(app, client, "/api/jobs/session", {"reference": ONE})

    # Assert
    assert job["state"] == JobState.DONE
    assert job["result"]["ok"].value is True
    assert job["result"]["since"].value is None
    found = history(logbook_path(), drive="hvc-022")
    assert [entry.kind for entry in found] == [EntryKind.CHECK]


def test_a_session_check_that_needed_retries_reports_the_drift(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE)))
    run(app, client, "/api/jobs/session", {})
    serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE), plan=FaultPlan(flaky_blocks={1: 2})))

    # Act
    job = run(app, client, "/api/jobs/session", {})

    # Assert
    assert job["state"] == JobState.DONE
    assert job["result"]["moved"] == [[0, 1]]
    assert job["result"]["ok"].value is False


@pytest.mark.usefixtures("attached")
def test_a_session_check_whose_logbook_cannot_be_read_fails_naming_it(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    store = tmp_path / "broken.sqlite3"
    store.write_bytes(b"not a database, only text that sqlite refuses to open " * 64)
    monkeypatch.setenv(LOGBOOK_ENV, str(store))

    # Act
    job = run(app, client, "/api/jobs/session", {})

    # Assert
    assert job["state"] == JobState.FAILED
    assert str(job["error"]).startswith(f"could not read the logbook at {store}: ")


@pytest.mark.usefixtures("attached")
def test_a_reference_that_is_not_an_image_is_refused_before_the_drive_opens(
    client: TestClient,
) -> None:
    # Arrange
    payload = {"reference": "not base64 at all!"}

    # Act
    answer = client.post("/api/jobs/session", json=payload)

    # Assert
    assert answer.status_code == BAD_REQUEST
