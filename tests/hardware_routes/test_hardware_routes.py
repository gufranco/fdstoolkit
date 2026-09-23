from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from fdstoolkit.build.blank import blank_image
from fdstoolkit.ui.app import create_app

OK = 200
BAD_REQUEST = 400
UNPROCESSABLE = 422
ONE_SIDE = blank_image(sides=1, headered=False, formatted=True, game_name="SMB")
ONE = base64.b64encode(ONE_SIDE).decode("ascii")


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(create_app())


def test_a_dump_runs_against_the_simulated_drive(client: TestClient) -> None:
    body = client.post("/api/dump", json={"source": ONE, "sides": 1}).json()

    assert body["size"] == len(ONE_SIDE)


def test_a_write_refuses_without_a_confirmation(client: TestClient) -> None:
    answer = client.post("/api/write", json={"data": ONE, "source": ONE})

    assert answer.status_code == UNPROCESSABLE
    assert "confirm" in answer.json()["detail"]


def test_a_confirmed_write_reports_what_it_did(client: TestClient) -> None:
    body = client.post(
        "/api/write",
        json={"data": ONE, "source": ONE, "confirm": True},
    ).json()

    assert body["rows"]


def test_a_surface_test_refuses_without_a_confirmation(client: TestClient) -> None:
    answer = client.post("/api/surface", json={"source": ONE})

    assert answer.status_code == UNPROCESSABLE


def test_a_confirmed_surface_test_reports_its_coverage(client: TestClient) -> None:
    body = client.post(
        "/api/surface",
        json={"source": ONE, "sides": 1, "quick": True, "confirm": True},
    ).json()

    assert body["rows"]


def test_a_surface_test_can_leave_the_disk_blank(client: TestClient) -> None:
    body = client.post(
        "/api/surface",
        json={
            "source": ONE,
            "sides": 1,
            "quick": True,
            "confirm": True,
            "finish": "blank",
        },
    ).json()

    assert body["rows"]


def test_an_unknown_finish_is_refused(client: TestClient) -> None:
    answer = client.post(
        "/api/surface",
        json={"source": ONE, "confirm": True, "finish": "nonsense"},
    )

    assert answer.status_code == BAD_REQUEST


def test_a_submission_refuses_a_simulated_log(client: TestClient) -> None:
    dumped = client.post("/api/dump", json={"source": ONE, "sides": 1}).json()

    answer = client.post(
        "/api/submit",
        json={"data": dumped["data"], "log": dumped["log"], "dumper": "someone"},
    )

    assert answer.status_code == BAD_REQUEST
    assert "simulated" in answer.json()["detail"]


def test_a_dump_carries_the_log_that_describes_it(client: TestClient) -> None:
    body = client.post("/api/dump", json={"source": ONE, "sides": 1}).json()

    assert body["log"]


def test_a_dump_from_a_drive_with_no_disk_is_refused(client: TestClient) -> None:
    empty = base64.b64encode(bytes(16)).decode("ascii")

    answer = client.post("/api/dump", json={"source": empty, "sides": 1})

    assert answer.status_code == BAD_REQUEST


def test_a_write_the_drive_cannot_take_is_reported(client: TestClient) -> None:
    two_sides = base64.b64encode(blank_image(sides=2, headered=False, formatted=True)).decode(
        "ascii"
    )

    answer = client.post(
        "/api/write",
        json={"data": two_sides, "source": ONE, "confirm": True},
    )

    assert answer.status_code == BAD_REQUEST


def test_a_surface_test_the_drive_refuses_is_reported(client: TestClient) -> None:
    empty = base64.b64encode(bytes(16)).decode("ascii")

    answer = client.post(
        "/api/surface",
        json={"source": empty, "sides": 1, "confirm": True},
    )

    assert answer.status_code == BAD_REQUEST


def test_a_log_that_is_not_a_log_is_refused(client: TestClient) -> None:
    rubbish = base64.b64encode(b"{}").decode("ascii")

    answer = client.post(
        "/api/submit",
        json={"data": ONE, "log": rubbish, "dumper": "someone"},
    )

    assert answer.status_code == BAD_REQUEST


def test_a_submission_from_a_hardware_log_renders(client: TestClient) -> None:
    dumped = client.post("/api/dump", json={"source": ONE, "sides": 1}).json()
    record = json.loads(base64.b64decode(dumped["log"]))
    record["simulated"] = False
    record["backend"] = "fdsstick"
    hardware = base64.b64encode(json.dumps(record).encode("utf-8")).decode("ascii")

    body = client.post(
        "/api/submit",
        json={
            "data": dumped["data"],
            "log": hardware,
            "dumper": "someone",
            "photos": ["media.jpg"],
        },
    ).json()

    assert "SHA-256 hash:" in body["text"]
    assert body["ok"]


def test_a_dump_of_more_sides_than_a_card_has_is_refused(client: TestClient) -> None:
    answer = client.post("/api/dump", json={"source": ONE, "sides": 4})

    assert answer.status_code == UNPROCESSABLE


def test_a_surface_test_of_more_sides_than_a_card_has_is_refused(client: TestClient) -> None:
    answer = client.post(
        "/api/surface",
        json={"source": ONE, "sides": 4, "confirm": True},
    )

    assert answer.status_code == UNPROCESSABLE


def test_a_source_with_no_blocks_is_refused(client: TestClient) -> None:
    empty = base64.b64encode(bytes(16)).decode("ascii")

    answer = client.post("/api/dump", json={"source": empty, "sides": 1})

    assert answer.status_code == BAD_REQUEST


def test_a_second_side_a_one_side_image_does_not_have_is_reported(client: TestClient) -> None:
    answer = client.post("/api/dump", json={"source": ONE, "sides": 2})

    assert answer.status_code == BAD_REQUEST


def test_a_surface_test_on_a_side_the_image_does_not_have_is_reported(
    client: TestClient,
) -> None:
    answer = client.post(
        "/api/surface",
        json={"source": ONE, "sides": 2, "confirm": True},
    )

    assert answer.status_code == BAD_REQUEST
