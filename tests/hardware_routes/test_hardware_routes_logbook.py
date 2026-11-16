from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from hardware_routes_kit import ONE, ONE_SIDE, disk_of, run

from fdstoolkit.history.entries import DRIVE_ENV, disk_key
from fdstoolkit.history.logbook import LOGBOOK_ENV, EntryKind, history, logbook_path
from fdstoolkit.ui.jobs import JobState

if TYPE_CHECKING:
    from drive_double import SimulatedDrive
    from fastapi import FastAPI
    from fastapi.testclient import TestClient


def _disk_id() -> str:
    key = disk_key(disk_of(ONE_SIDE))
    assert key is not None
    return key.id


@pytest.mark.usefixtures("attached")
def test_a_dump_job_logs_under_the_disk_and_the_drive(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setenv(DRIVE_ENV, "hvc-022")

    # Act
    job = run(app, client, "/api/jobs/dump", {"sides": 1})

    # Assert
    assert job["state"] == JobState.DONE
    found = history(logbook_path(), disk=_disk_id())
    assert [(entry.kind, entry.drive) for entry in found] == [(EntryKind.DUMP, "hvc-022")]


@pytest.mark.usefixtures("attached")
def test_a_dump_job_that_cannot_log_fails_naming_it_and_keeps_the_image(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"")
    store = blocker / "logbook.sqlite3"
    monkeypatch.setenv(LOGBOOK_ENV, str(store))

    # Act
    job = run(app, client, "/api/jobs/dump", {"sides": 1})

    # Assert
    assert job["state"] == JobState.FAILED
    assert str(job["error"]).startswith(f"could not write the logbook at {store}: ")
    assert job["kept"]["name"] == "dump.fds"


@pytest.mark.usefixtures("attached")
def test_a_live_calibration_job_logs_under_the_drive(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setenv(DRIVE_ENV, "twin")

    # Act
    job = run(app, client, "/api/jobs/calibrate", {"mode": "head", "reference": ONE, "passes": 1})

    # Assert
    assert job["state"] == JobState.DONE
    found = history(logbook_path(), drive="twin")
    assert [(entry.kind, entry.disk) for entry in found] == [(EntryKind.CALIBRATION, _disk_id())]


def test_a_live_calibration_without_a_reference_logs_the_drive_alone(
    app: FastAPI, client: TestClient, attached: SimulatedDrive
) -> None:
    # Arrange
    expected = JobState.DONE

    # Act
    job = run(app, client, "/api/jobs/calibrate", {"mode": "head", "passes": 1})

    # Assert
    assert job["state"] == expected
    assert attached.closed
    found = history(logbook_path(), drive="drive")
    assert [entry.title for entry in found] == ["the disk in the drive"]


@pytest.mark.usefixtures("attached")
def test_a_calibration_job_that_cannot_log_fails_naming_it(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"")
    store = blocker / "logbook.sqlite3"
    monkeypatch.setenv(LOGBOOK_ENV, str(store))

    # Act
    job = run(app, client, "/api/jobs/calibrate", {"mode": "head", "passes": 1})

    # Assert
    assert job["state"] == JobState.FAILED
    assert str(job["error"]).startswith(f"could not write the logbook at {store}: ")
    assert job["kept"].value is None
