from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

import pytest
from drive_double import SimulatedDrive
from fastapi.testclient import TestClient
from hardware_routes_kit import ONE_SIDE, disk_of, run, serve

from fdstoolkit.ui.app import create_app
from fdstoolkit.ui.jobs import JobState

if TYPE_CHECKING:
    from fastapi import FastAPI

UNPROCESSABLE: Final = 422


@pytest.fixture(name="app")
def app_fixture() -> FastAPI:
    return create_app()


@pytest.fixture(name="client")
def client_fixture(app: FastAPI) -> TestClient:
    return TestClient(app, base_url="http://127.0.0.1")


def test_an_erase_job_leaves_no_block_and_offers_the_backup(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE)))

    # Act
    job = run(app, client, "/api/jobs/erase", {"confirm": True})

    # Assert
    assert job["state"] == JobState.DONE
    assert job["result"]["headline"] == "every side reads back with no block"
    assert job["result"]["ok"].value is True
    assert job["result"]["file"]["name"] == "before.fds"
    assert drive.disk is not None
    assert drive.disk.sides[0].blocks == ()


def test_an_erase_job_needs_a_confirmation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE)))

    # Act
    answer = client.post("/api/jobs/erase", json={})

    # Assert
    assert answer.status_code == UNPROCESSABLE
    assert drive.write_count == 0


class LeavesTheLastBlock(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        current = self.disk
        assert current is not None
        kept = [block.payload for block in current.sides[side].blocks[-1:]]
        super().write_side(side, [*blocks, *kept])


def test_an_erase_job_that_leaves_a_block_says_so(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    serve(monkeypatch, LeavesTheLastBlock(disk_of(ONE_SIDE)))

    # Act
    job = run(app, client, "/api/jobs/erase", {"confirm": True})

    # Assert
    assert job["result"]["ok"].value is False
    assert job["result"]["headline"] == "1 block(s) did not read back as written"
