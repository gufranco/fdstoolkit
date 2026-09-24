from __future__ import annotations

import base64

import pytest
from drive_double import SimulatedDrive
from fastapi.testclient import TestClient

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.disk import Disk
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError
from fdstoolkit.ui.app import create_app

OK = 200
BAD_REQUEST = 400
CONFLICT = 409
UNPROCESSABLE = 422
ONE_SIDE = blank_image(sides=1, headered=False, formatted=True, game_name="SMB")
TWO_SIDE = blank_image(sides=2, headered=False, formatted=True, game_name="SMB")
ONE = base64.b64encode(ONE_SIDE).decode("ascii")
TWO = base64.b64encode(TWO_SIDE).decode("ascii")


def disk_of(image: bytes) -> Disk:
    disk, _ = decode(image)
    return disk


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(name="attached")
def attached_fixture(monkeypatch: pytest.MonkeyPatch) -> list[SimulatedDrive]:
    made: list[SimulatedDrive] = []

    def opener() -> SimulatedDrive:
        if not made:
            made.append(SimulatedDrive(disk_of(ONE_SIDE)))
        return made[0]

    monkeypatch.setattr("fdstoolkit.ui.hardware_routes.open_fdsstick", opener)
    return made


@pytest.fixture(name="absent")
def absent_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    def opener() -> SimulatedDrive:
        message = "no FDSStick is attached"
        raise HardwareFaultError(message, kind=FaultKind.LINK)

    monkeypatch.setattr("fdstoolkit.ui.hardware_routes.open_fdsstick", opener)


@pytest.mark.usefixtures("absent")
@pytest.mark.parametrize(
    ("route", "payload"),
    [
        ("/api/dump", {"sides": 1}),
        ("/api/write", {"data": ONE, "confirm": True}),
        ("/api/surface", {"sides": 1, "quick": True, "confirm": True}),
    ],
)
def test_a_disk_command_refuses_when_no_stick_is_attached(
    client: TestClient,
    route: str,
    payload: dict[str, object],
) -> None:
    answer = client.post(route, json=payload)

    assert answer.status_code == CONFLICT
    assert "FDSStick" in answer.json()["detail"]


@pytest.mark.usefixtures("attached")
def test_a_dump_reads_the_disk_in_the_drive(client: TestClient) -> None:
    body = client.post("/api/dump", json={"sides": 1}).json()

    assert body["size"] == len(ONE_SIDE)


def test_a_write_refuses_without_a_confirmation(client: TestClient) -> None:
    answer = client.post("/api/write", json={"data": ONE})

    assert answer.status_code == UNPROCESSABLE
    assert "confirm" in answer.json()["detail"]


@pytest.mark.usefixtures("attached")
def test_a_confirmed_write_reports_what_it_did(client: TestClient) -> None:
    body = client.post("/api/write", json={"data": ONE, "confirm": True}).json()

    assert body["rows"]


def test_a_surface_test_refuses_without_a_confirmation(client: TestClient) -> None:
    answer = client.post("/api/surface", json={})

    assert answer.status_code == UNPROCESSABLE


@pytest.mark.usefixtures("attached")
def test_a_confirmed_surface_test_reports_its_coverage(client: TestClient) -> None:
    body = client.post(
        "/api/surface",
        json={"sides": 1, "quick": True, "confirm": True},
    ).json()

    assert body["rows"]


@pytest.mark.usefixtures("attached")
def test_a_surface_test_can_leave_the_disk_blank(client: TestClient) -> None:
    body = client.post(
        "/api/surface",
        json={"sides": 1, "quick": True, "confirm": True, "finish": "blank"},
    ).json()

    assert body["rows"]


@pytest.mark.usefixtures("attached")
def test_an_unknown_finish_is_refused(client: TestClient) -> None:
    answer = client.post("/api/surface", json={"confirm": True, "finish": "nonsense"})

    assert answer.status_code == BAD_REQUEST


def test_a_dump_from_a_drive_with_no_disk_is_refused(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def opener() -> SimulatedDrive:
        return SimulatedDrive(None)

    monkeypatch.setattr("fdstoolkit.ui.hardware_routes.open_fdsstick", opener)

    answer = client.post("/api/dump", json={"sides": 1})

    assert answer.status_code == BAD_REQUEST


@pytest.mark.usefixtures("attached")
def test_a_write_the_drive_cannot_take_is_reported(client: TestClient) -> None:
    answer = client.post("/api/write", json={"data": TWO, "confirm": True})

    assert answer.status_code == BAD_REQUEST


def test_a_surface_test_with_no_disk_in_the_drive_is_refused(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def opener() -> SimulatedDrive:
        return SimulatedDrive(None)

    monkeypatch.setattr("fdstoolkit.ui.hardware_routes.open_fdsstick", opener)

    answer = client.post("/api/surface", json={"sides": 1, "confirm": True})

    assert answer.status_code == BAD_REQUEST


def test_a_dump_of_more_sides_than_a_card_has_is_refused(client: TestClient) -> None:
    answer = client.post("/api/dump", json={"sides": 4})

    assert answer.status_code == UNPROCESSABLE


def test_a_surface_test_of_more_sides_than_a_card_has_is_refused(client: TestClient) -> None:
    answer = client.post("/api/surface", json={"sides": 4, "confirm": True})

    assert answer.status_code == UNPROCESSABLE


@pytest.mark.usefixtures("attached")
def test_a_second_side_a_one_side_disk_does_not_have_is_reported(client: TestClient) -> None:
    answer = client.post("/api/dump", json={"sides": 2})

    assert answer.status_code == BAD_REQUEST


@pytest.mark.usefixtures("attached")
def test_a_surface_test_on_a_side_the_disk_does_not_have_is_reported(
    client: TestClient,
) -> None:
    answer = client.post("/api/surface", json={"sides": 2, "confirm": True})

    assert answer.status_code == BAD_REQUEST
