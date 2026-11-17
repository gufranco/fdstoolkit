from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

import pytest
from drive_double import FaultPlan, SimulatedDrive
from fastapi.testclient import TestClient
from hardware_routes_kit import ONE, ONE_SIDE, SETTLE, disk_of, long_image, run, serve

from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Disk
from fdstoolkit.core.files import extract_files
from fdstoolkit.edit.files import FileSpec, insert_file
from fdstoolkit.quality.checker import CHECKER_ALONE, CHECKER_BYTES
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


def test_a_duplicate_job_asks_for_each_disk_and_counts_the_copies(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE)))
    started = client.post("/api/jobs/duplicate", json={"data": ONE, "count": 2, "confirm": True})
    job_id = started.json()["id"]

    # Act
    answers = [answer_when_asked(app, client, job_id) for _ in range(2)]

    # Assert
    assert answers == [
        "put blank disk 1 of 2 in the drive, then confirm",
        "put blank disk 2 of 2 in the drive, then confirm",
    ]
    assert app.state.jobs.wait(job_id, SETTLE)
    done = client.get(f"/api/jobs/{job_id}").json()
    assert done["result"]["headline"] == "2 of 2 copies verified"
    assert done["result"]["ok"] is True


def test_a_duplicate_job_refuses_a_long_side(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE)))
    payload = {"data": long_image(), "confirm": True}

    # Act
    answer = client.post("/api/jobs/duplicate", json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE
    assert drive.write_count == 0


def answer_when_asked(app: FastAPI, client: TestClient, job_id: str) -> str:
    assert app.state.jobs.wait_for_state(job_id, JobState.WAITING, SETTLE)
    prompt = str(client.get(f"/api/jobs/{job_id}").json()["prompt"])
    client.post(f"/api/jobs/{job_id}/answer", json={"yes": True})
    return prompt


def test_a_refresh_job_offers_the_rebuilt_image(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE)))

    # Act
    job = run(app, client, "/api/jobs/refresh", {"confirm": True})

    # Assert
    assert job["state"] == JobState.DONE
    assert job["result"]["ok"].value is True
    assert job["result"]["file"]["name"] == "refreshed.fds"
    assert str(job["result"]["headline"]).startswith("the disk reads back as rebuilt")
    assert drive.write_count == 1


def test_a_refresh_job_whose_readback_differs_says_how_many_blocks(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    serve(monkeypatch, LeavesTheLastBlock(disk_of(ONE_SIDE)))

    # Act
    job = run(app, client, "/api/jobs/refresh", {"confirm": True})

    # Assert
    assert job["result"]["ok"].value is False
    assert job["result"]["rows"][0]["block"] == 2


def test_a_refresh_job_that_cannot_settle_fails_and_writes_nothing(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    plan = FaultPlan(bad_crc_blocks=frozenset({1}))
    drive = serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE), plan=plan))

    # Act
    job = run(app, client, "/api/jobs/refresh", {"confirm": True, "passes": 1, "retries": 0})

    # Assert
    assert job["state"] == JobState.FAILED
    assert "never read clean" in str(job["error"])
    assert drive.write_count == 0


def _saved_game(save: bytes) -> Disk:
    disk = disk_of(ONE_SIDE)
    for name in ("MAIN", "SAVEDATA"):
        data = save if name == "SAVEDATA" else bytes([0xAA]) * 32
        disk = insert_file(
            disk, side=0, spec=FileSpec(name=name, address=0x6000, kind=FileKind.PROGRAM, data=data)
        )
    return disk


def test_a_save_backed_up_by_one_job_is_restored_by_another(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    serve(monkeypatch, SimulatedDrive(_saved_game(bytes(range(64)))))
    kept = run(app, client, "/api/jobs/save-backup", {})
    drive = serve(monkeypatch, SimulatedDrive(_saved_game(bytes(64))))
    payload: dict[str, object] = {
        "saved": str(kept["result"]["file"]["data"].value),
        "confirm": True,
    }

    # Act
    job = run(app, client, "/api/jobs/save-restore", payload)

    # Assert
    assert kept["result"]["file"]["name"] == "save.json"
    assert job["result"]["ok"].value is True
    assert job["result"]["file"]["name"] == "before.fds"
    assert drive.disk is not None
    files = {entry.name: entry.data for entry in extract_files(drive.disk)}
    assert files["SAVEDATA"] == bytes(range(64))


def test_a_restore_that_leaves_a_block_names_it(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    serve(monkeypatch, SimulatedDrive(_saved_game(bytes(range(64)))))
    kept = run(app, client, "/api/jobs/save-backup", {})
    serve(monkeypatch, LeavesTheLastBlock(_saved_game(bytes(64))))
    payload: dict[str, object] = {
        "saved": str(kept["result"]["file"]["data"].value),
        "confirm": True,
    }

    # Act
    job = run(app, client, "/api/jobs/save-restore", payload)

    # Assert
    assert job["result"]["ok"].value is False
    assert str(job["result"]["rows"][0]["finding"]).startswith("is old data past the end")


def test_a_restore_of_something_that_is_not_a_save_is_refused(client: TestClient) -> None:
    # Arrange
    payload = {"saved": base64.b64encode(b"{}").decode(), "confirm": True}

    # Act
    answer = client.post("/api/jobs/save-restore", json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE
    assert answer.json()["detail"] == "this is not a save backup that disk-save wrote"


def test_a_surface_job_with_the_checker_pattern_reads_it_back(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE)))
    payload: dict[str, object] = {"pattern": "checker", "confirm": True}

    # Act
    job = run(app, client, "/api/jobs/surface", payload)

    # Assert
    assert job["state"] == JobState.DONE
    assert job["result"]["ok"].value is True
    assert job["result"]["headline"] == f"side 0: all {CHECKER_BYTES} pattern bytes read back"
    assert job["result"]["file"]["name"] == "before.fds"


def test_a_checker_job_that_does_not_read_back_says_so(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    serve(monkeypatch, DropsTheTestBlock(disk_of(ONE_SIDE)))

    # Act
    job = run(app, client, "/api/jobs/surface", {"pattern": "checker", "confirm": True})

    # Assert
    assert job["result"]["ok"].value is False


def test_a_checker_job_with_cycle_options_is_refused(client: TestClient) -> None:
    # Arrange
    payload = {"pattern": "checker", "quick": True, "confirm": True}

    # Act
    answer = client.post("/api/jobs/surface", json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE
    assert answer.json()["detail"] == CHECKER_ALONE


def test_a_checker_job_needs_a_confirmation(client: TestClient) -> None:
    # Arrange
    payload = {"pattern": "checker"}

    # Act
    answer = client.post("/api/jobs/surface", json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE


class DropsTheTestBlock(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        super().write_side(side, blocks[:-1])
