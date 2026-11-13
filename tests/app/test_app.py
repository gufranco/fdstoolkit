from __future__ import annotations

import base64
import inspect
import logging
import re
import threading
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app as cli_app
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.diskinfo import PROFILES
from fdstoolkit.doctor import CheckStatus, diagnose
from fdstoolkit.identify.hashes import digests_of
from fdstoolkit.ui.app import (
    DEVICE_CHECK,
    MAX_BODY_BYTES,
    SHUTDOWN_WAIT_S,
    create_app,
)
from fdstoolkit.ui.body_limit import TOO_LARGE
from fdstoolkit.ui.forms import forms, opens_a_drive
from fdstoolkit.ui.jobs import Controls

OK = 200
BAD_REQUEST = 400
UNPROCESSABLE = 422
IMAGE = blank_image(sides=2, headered=False, formatted=True, game_name="SMB")
ENCODED = base64.b64encode(IMAGE).decode("ascii")


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(create_app(), base_url="http://127.0.0.1")


def test_the_page_is_served(client: TestClient) -> None:
    # Arrange
    route = "/"

    # Act
    answer = client.get(route)

    # Assert
    assert answer.status_code == OK
    assert "<!doctype html>" in answer.text.lower()


def test_the_catalogue_lists_every_profile(client: TestClient) -> None:
    # Arrange
    expected = set(PROFILES)

    # Act
    body = client.get("/api/catalogue").json()

    # Assert
    assert {entry["name"] for entry in body["profiles"]} == expected
    assert body["version"]


def test_the_catalogue_lists_every_command_the_page_covers(client: TestClient) -> None:
    # Arrange
    route = "/api/catalogue"

    # Act
    body = client.get(route).json()

    # Assert
    assert "verify" in body["commands"]
    assert "grade" in body["commands"]


def test_the_install_check_is_not_on_the_page(client: TestClient) -> None:
    # Arrange
    route = "/api/doctor"

    # Act
    answer = client.get(route)

    # Assert
    assert answer.status_code == 404


def test_info_describes_every_side(client: TestClient) -> None:
    # Arrange
    expected = 2

    # Act
    body = client.post("/api/info", json={"data": ENCODED}).json()

    # Assert
    assert len(body["sides"]) == expected
    assert body["sides"][0]["index"] == 0


def test_verify_reports_the_same_findings_the_command_would(client: TestClient) -> None:
    # Arrange
    _, findings = decode(IMAGE)

    # Act
    body = client.post("/api/verify", json={"data": ENCODED}).json()

    # Assert
    assert body["ok"] is (not findings)
    assert len(body["diagnostics"]) == len(findings)


def test_hash_matches_the_command_byte_for_byte(client: TestClient) -> None:
    # Arrange
    expected = digests_of(IMAGE)

    # Act
    body = client.post("/api/hash", json={"data": ENCODED}).json()

    # Assert
    assert body["whole"]["sha256"] == expected.sha256
    assert body["whole"]["crc32"] == expected.crc32
    assert len(body["sides"]) == 2


def test_hash_carries_the_canonical_digest(client: TestClient) -> None:
    # Arrange
    payload = {"data": ENCODED, "profile": "release"}

    # Act
    body = client.post("/api/hash", json=payload).json()

    # Assert
    assert body["canonical"].startswith("fdstoolkit:v1:release/")


def test_an_unknown_profile_is_refused(client: TestClient) -> None:
    # Arrange
    route = "/api/hash"
    payload = {"data": ENCODED, "profile": "nonsense"}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == BAD_REQUEST


def test_grade_reports_a_confidence(client: TestClient) -> None:
    # Arrange
    payload = {"data": ENCODED}

    # Act
    body = client.post("/api/grade", json=payload).json()

    # Assert
    assert body["grade"]
    assert 0.0 <= body["confidence"] <= 1.0
    assert body["reasons"]


def test_reads_compares_repeated_dumps(client: TestClient) -> None:
    # Arrange
    expected = 2

    # Act
    body = client.post("/api/reads", json={"images": [ENCODED, ENCODED]}).json()

    # Assert
    assert body["passes"] == expected
    assert body["stability"] == pytest.approx(1.0)


def test_reads_needs_more_than_one_image(client: TestClient) -> None:
    # Arrange
    route = "/api/reads"
    payload = {"images": [ENCODED]}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE


def test_an_image_bundling_more_than_one_disk_is_refused(client: TestClient) -> None:
    # Arrange
    three = blank_image(sides=2, headered=False, formatted=True) + blank_image(
        sides=1, headered=False, formatted=True
    )

    # Act
    answer = client.post("/api/verify", json={"data": base64.b64encode(three).decode("ascii")})

    # Assert
    assert answer.status_code == BAD_REQUEST
    assert "holds 3 sides" in answer.json()["detail"]


def test_blank_builds_an_image(client: TestClient) -> None:
    # Arrange
    expected = len(blank_image(sides=1, headered=False, formatted=True))

    # Act
    body = client.post("/api/blank", json={"sides": 1, "formatted": True}).json()

    # Assert
    assert body["size"] == expected
    assert base64.b64decode(body["data"])


def test_a_blank_with_no_sides_is_refused(client: TestClient) -> None:
    # Arrange
    route = "/api/blank"
    payload = {"sides": 0}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE


@pytest.mark.parametrize("sides", [3, -1, 2.0, "2", True, 1.5])
def test_a_blank_takes_only_the_integer_one_or_two(client: TestClient, sides: object) -> None:
    # Arrange
    route = "/api/blank"
    payload = {"sides": sides}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE


def test_a_two_side_blank_is_built(client: TestClient) -> None:
    # Arrange
    expected = len(blank_image(sides=2, headered=False, formatted=True))

    # Act
    body = client.post("/api/blank", json={"sides": 2, "formatted": True}).json()

    # Assert
    assert body["size"] == expected


def test_hash_offers_the_canonical_image_when_asked(client: TestClient) -> None:
    # Arrange
    payload = {"data": ENCODED, "profile": "release", "canonical_image": True}

    # Act
    body = client.post("/api/hash", json=payload).json()

    # Assert
    assert body["file"]["name"]
    assert base64.b64decode(body["file"]["data"])


def test_hash_offers_no_image_unless_asked(client: TestClient) -> None:
    # Arrange
    expected = None

    # Act
    body = client.post("/api/hash", json={"data": ENCODED}).json()

    # Assert
    assert body["file"] is expected


def test_convert_produces_a_qd(client: TestClient) -> None:
    # Arrange
    payload = {"data": ENCODED, "to_qd": True}

    # Act
    body = client.post("/api/convert", json=payload).json()

    # Assert
    assert body["name"].endswith(".qd")
    assert body["size"] > len(IMAGE)


def test_an_image_that_is_not_base64_is_refused(client: TestClient) -> None:
    # Arrange
    route = "/api/info"
    payload = {"data": "not base64 at all!!"}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == BAD_REQUEST


def test_an_image_from_another_system_is_refused(client: TestClient) -> None:
    # Arrange
    hxc = base64.b64encode(b"HXCQDDRV" + bytes(56)).decode("ascii")

    # Act
    answer = client.post("/api/info", json={"data": hxc})

    # Assert
    assert answer.status_code == BAD_REQUEST
    assert "not a Famicom Disk System image" in answer.json()["detail"]


def test_a_damaged_image_is_reported_rather_than_refused(client: TestClient) -> None:
    # Arrange
    damaged = base64.b64encode(bytes(16)).decode("ascii")

    # Act
    answer = client.post("/api/verify", json={"data": damaged})

    # Assert
    assert answer.status_code == OK
    assert answer.json()["diagnostics"]


def test_convert_rewrites_an_fds_without_a_header(client: TestClient) -> None:
    # Arrange
    payload = {"data": ENCODED, "to_qd": False}

    # Act
    body = client.post("/api/convert", json=payload).json()

    # Assert
    assert body["name"].endswith(".fds")
    assert body["size"] == len(IMAGE)


def test_convert_can_add_a_header(client: TestClient) -> None:
    # Arrange
    expected = len(IMAGE)

    # Act
    body = client.post(
        "/api/convert",
        json={"data": ENCODED, "to_qd": False, "headered": True},
    ).json()

    # Assert
    assert body["size"] > expected


def test_grade_folds_in_a_second_read(client: TestClient) -> None:
    # Arrange
    payload = {"data": ENCODED, "reads": [ENCODED]}

    # Act
    body = client.post("/api/grade", json=payload).json()

    # Assert
    assert body["grade"]
    assert body["reasons"]


def test_a_canonical_image_carries_a_profile_in_its_name(client: TestClient) -> None:
    # Arrange
    expected = "smb.data.fds"

    # Act
    body = client.post(
        "/api/hash",
        json={"data": ENCODED, "name": "smb.fds", "profile": "data", "canonical_image": True},
    ).json()

    # Assert
    assert body["file"]["name"] == expected


def test_a_body_larger_than_the_ceiling_is_refused(client: TestClient) -> None:
    # Arrange
    route = "/api/verify"
    payload = {"data": "AA=="}
    headers = {"content-length": str(MAX_BODY_BYTES + 1)}

    # Act
    answer = client.post(
        route,
        json=payload,
        headers=headers,
    )

    # Assert
    assert answer.status_code == TOO_LARGE


def test_a_body_inside_the_ceiling_is_accepted(client: TestClient) -> None:
    # Arrange
    route = "/api/verify"
    payload = {"data": ENCODED}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code != TOO_LARGE


def test_the_device_route_reports_what_the_check_found(client: TestClient) -> None:
    # Arrange
    answer = client.get("/api/hardware").json()

    # Act
    found = next(check for check in diagnose().checks if check.name == DEVICE_CHECK)

    # Assert
    assert answer["detail"] == found.detail
    assert answer["connected"] is (found.status is CheckStatus.OK)


def test_only_the_commands_that_open_a_drive_are_marked() -> None:
    # Arrange
    expected = {"calibrate", "dump", "write", "surface"}

    # Act
    marked = {form.command for form in forms() if form.needs_hardware}

    # Assert
    assert marked == expected


def test_a_command_whose_source_is_unreadable_is_marked_rather_than_cleared(tmp_path: Path) -> None:
    # Arrange
    def installed() -> None:
        return None

    missing = str(tmp_path / "removed.py")
    hidden = types.FunctionType(installed.__code__.replace(co_filename=missing), {})

    # Act
    marked = opens_a_drive(hidden)

    # Assert
    assert marked is True


def test_every_marked_commandopens_a_drive_in_the_cli() -> None:
    # Arrange
    marked = {form.command for form in forms() if form.needs_hardware}

    # Act
    opens = {
        registered.name or registered.callback.__name__
        for registered in cli_app.registered_commands
        if registered.callback is not None
        and "open_drive(" in inspect.getsource(registered.callback)
    }

    # Assert
    assert marked == opens


def test_status_reports_only_the_device_checks(client: TestClient) -> None:
    # Arrange
    route = "/api/status"

    # Act
    body = client.get(route).json()

    # Assert
    names = {check["name"] for check in body["checks"]}
    assert "fdsstick" in names
    assert "python" not in names
    assert isinstance(body["healthy"], bool)


def test_an_unexpected_failure_answers_a_reference_the_terminal_log_carries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    app = create_app()

    def broken() -> None:
        message = "the parser met a byte it did not expect"
        raise RuntimeError(message)

    app.add_api_route("/api/broken", broken, methods=["GET"])
    answer = TestClient(app, raise_server_exceptions=False, base_url="http://127.0.0.1").get(
        "/api/broken"
    )
    detail = answer.json()["detail"]

    # Act
    reference = re.search(r"reference ([0-9a-f]{12})\.", detail)

    # Assert
    assert answer.status_code == 500
    assert "the parser met a byte" not in detail
    assert reference is not None
    assert any(
        reference.group(1) in record.getMessage() and record.exc_info for record in caplog.records
    )


class Nothing(BaseModel):
    pass


def test_stopping_the_server_mid_write_says_the_disk_may_be_half_written(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    app = create_app()
    release = threading.Event()

    def work(controls: Controls) -> Nothing:
        del controls
        release.wait(SHUTDOWN_WAIT_S * 5)
        return Nothing()

    with caplog.at_level(logging.WARNING), TestClient(app, base_url="http://127.0.0.1"):
        app.state.jobs.start("write", writes=True, work=work)

    # Act
    release.set()

    # Assert
    assert any("may be half written" in record.getMessage() for record in caplog.records)


def test_stopping_the_server_mid_read_says_nothing_was_written(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    app = create_app()
    release = threading.Event()

    def work(controls: Controls) -> Nothing:
        del controls
        release.wait(SHUTDOWN_WAIT_S * 5)
        return Nothing()

    with caplog.at_level(logging.WARNING), TestClient(app, base_url="http://127.0.0.1"):
        app.state.jobs.start("dump", writes=False, work=work)

    # Act
    release.set()

    # Assert
    assert any("nothing was written" in record.getMessage() for record in caplog.records)


def test_stopping_an_idle_server_warns_of_nothing(caplog: pytest.LogCaptureFixture) -> None:
    # Arrange
    app = create_app()

    # Act
    with caplog.at_level(logging.WARNING), TestClient(app, base_url="http://127.0.0.1"):
        pass

    # Assert
    assert not any("still running" in record.getMessage() for record in caplog.records)
