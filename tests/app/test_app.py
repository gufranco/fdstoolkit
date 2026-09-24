from __future__ import annotations

import base64
import inspect
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app as cli_app
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.raw import pack_raw03
from fdstoolkit.core.diskinfo import PROFILES
from fdstoolkit.doctor import CheckStatus, diagnose
from fdstoolkit.identify.hashes import digests_of
from fdstoolkit.ui.app import (
    DEVICE_CHECK,
    MAX_BODY_BYTES,
    TOO_LARGE,
    create_app,
)
from fdstoolkit.ui.forms import forms, opens_a_drive

OK = 200
BAD_REQUEST = 400
UNPROCESSABLE = 422
IMAGE = blank_image(sides=2, headered=False, formatted=True, game_name="SMB")
ENCODED = base64.b64encode(IMAGE).decode("ascii")


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(create_app())


def test_the_page_is_served(client: TestClient) -> None:
    answer = client.get("/")

    assert answer.status_code == OK
    assert "<!doctype html>" in answer.text.lower()


def test_the_catalogue_lists_every_profile(client: TestClient) -> None:
    body = client.get("/api/catalogue").json()

    assert {entry["name"] for entry in body["profiles"]} == set(PROFILES)
    assert body["version"]


def test_the_catalogue_lists_every_command_the_page_covers(client: TestClient) -> None:
    body = client.get("/api/catalogue").json()

    assert "verify" in body["commands"]
    assert "grade" in body["commands"]


def test_doctor_is_reachable(client: TestClient) -> None:
    body = client.get("/api/doctor").json()

    names = {check["name"] for check in body["checks"]}
    assert "codec" in names
    assert "identity" in names
    assert isinstance(body["healthy"], bool)


def test_info_describes_every_side(client: TestClient) -> None:
    body = client.post("/api/info", json={"data": ENCODED}).json()

    assert len(body["sides"]) == 2
    assert body["sides"][0]["index"] == 0


def test_verify_reports_the_same_findings_the_command_would(client: TestClient) -> None:
    _, findings = decode(IMAGE)

    body = client.post("/api/verify", json={"data": ENCODED}).json()

    assert body["ok"] is (not findings)
    assert len(body["diagnostics"]) == len(findings)


def test_hash_matches_the_command_byte_for_byte(client: TestClient) -> None:
    expected = digests_of(IMAGE)

    body = client.post("/api/hash", json={"data": ENCODED}).json()

    assert body["whole"]["sha256"] == expected.sha256
    assert body["whole"]["crc32"] == expected.crc32
    assert len(body["sides"]) == 2


def test_hash_carries_the_canonical_digest(client: TestClient) -> None:
    body = client.post("/api/hash", json={"data": ENCODED, "profile": "release"}).json()

    assert body["canonical"].startswith("fdstoolkit:v1:release/")


def test_an_unknown_profile_is_refused(client: TestClient) -> None:
    answer = client.post("/api/hash", json={"data": ENCODED, "profile": "nonsense"})

    assert answer.status_code == BAD_REQUEST


def test_grade_reports_a_confidence(client: TestClient) -> None:
    body = client.post("/api/grade", json={"data": ENCODED}).json()

    assert body["grade"]
    assert 0.0 <= body["confidence"] <= 1.0
    assert body["reasons"]


def test_reads_compares_repeated_dumps(client: TestClient) -> None:
    body = client.post("/api/reads", json={"images": [ENCODED, ENCODED]}).json()

    assert body["passes"] == 2
    assert body["stability"] == pytest.approx(1.0)


def test_reads_needs_more_than_one_image(client: TestClient) -> None:
    answer = client.post("/api/reads", json={"images": [ENCODED]})

    assert answer.status_code == UNPROCESSABLE


def test_an_image_bundling_more_than_one_disk_is_refused(client: TestClient) -> None:
    three = blank_image(sides=2, headered=False, formatted=True) + blank_image(
        sides=1, headered=False, formatted=True
    )

    answer = client.post("/api/verify", json={"data": base64.b64encode(three).decode("ascii")})

    assert answer.status_code == BAD_REQUEST
    assert "holds 3 sides" in answer.json()["detail"]


def test_blank_builds_an_image(client: TestClient) -> None:
    body = client.post("/api/blank", json={"sides": 1, "formatted": True}).json()

    assert body["size"] == len(blank_image(sides=1, headered=False, formatted=True))
    assert base64.b64decode(body["data"])


def test_a_blank_with_no_sides_is_refused(client: TestClient) -> None:
    answer = client.post("/api/blank", json={"sides": 0})

    assert answer.status_code == UNPROCESSABLE


@pytest.mark.parametrize("sides", [3, -1, 2.0, "2", True, 1.5])
def test_a_blank_takes_only_the_integer_one_or_two(client: TestClient, sides: object) -> None:
    answer = client.post("/api/blank", json={"sides": sides})

    assert answer.status_code == UNPROCESSABLE


def test_a_two_side_blank_is_built(client: TestClient) -> None:
    body = client.post("/api/blank", json={"sides": 2, "formatted": True}).json()

    assert body["size"] == len(blank_image(sides=2, headered=False, formatted=True))


def test_canon_writes_the_canonical_image(client: TestClient) -> None:
    body = client.post("/api/canon", json={"data": ENCODED, "profile": "release"}).json()

    assert body["name"]
    assert base64.b64decode(body["data"])


def test_convert_produces_a_qd(client: TestClient) -> None:
    body = client.post("/api/convert", json={"data": ENCODED, "to_qd": True}).json()

    assert body["name"].endswith(".qd")
    assert body["size"] > len(IMAGE)


def test_an_image_that_is_not_base64_is_refused(client: TestClient) -> None:
    answer = client.post("/api/info", json={"data": "not base64 at all!!"})

    assert answer.status_code == BAD_REQUEST


def test_an_image_from_another_system_is_refused(client: TestClient) -> None:
    hxc = base64.b64encode(b"HXCQDDRV" + bytes(56)).decode("ascii")

    answer = client.post("/api/info", json={"data": hxc})

    assert answer.status_code == BAD_REQUEST
    assert "not a Famicom Disk System image" in answer.json()["detail"]


def test_a_damaged_image_is_reported_rather_than_refused(client: TestClient) -> None:
    damaged = base64.b64encode(bytes(16)).decode("ascii")

    answer = client.post("/api/verify", json={"data": damaged})

    assert answer.status_code == OK
    assert answer.json()["diagnostics"]


def test_the_api_documentation_is_served(client: TestClient) -> None:
    assert client.get("/docs").status_code == OK


def test_convert_rewrites_an_fds_without_a_header(client: TestClient) -> None:
    body = client.post("/api/convert", json={"data": ENCODED, "to_qd": False}).json()

    assert body["name"].endswith(".fds")
    assert body["size"] == len(IMAGE)


def test_convert_can_add_a_header(client: TestClient) -> None:
    body = client.post(
        "/api/convert",
        json={"data": ENCODED, "to_qd": False, "headered": True},
    ).json()

    assert body["size"] > len(IMAGE)


def test_grade_folds_in_a_second_read(client: TestClient) -> None:
    body = client.post("/api/grade", json={"data": ENCODED, "reads": [ENCODED]}).json()

    assert body["grade"]
    assert body["reasons"]


def test_a_canon_image_carries_a_profile_in_its_name(client: TestClient) -> None:
    body = client.post(
        "/api/canon",
        json={"data": ENCODED, "name": "smb.fds", "profile": "data"},
    ).json()

    assert body["name"] == "smb.data.fds"


def test_a_body_larger_than_the_ceiling_is_refused(client: TestClient) -> None:
    answer = client.post(
        "/api/verify",
        json={"data": "AA=="},
        headers={"content-length": str(MAX_BODY_BYTES + 1)},
    )

    assert answer.status_code == TOO_LARGE


def test_a_body_inside_the_ceiling_is_accepted(client: TestClient) -> None:
    answer = client.post("/api/verify", json={"data": ENCODED})

    assert answer.status_code != TOO_LARGE


def test_the_device_route_reports_what_the_check_found(client: TestClient) -> None:
    answer = client.get("/api/hardware").json()
    found = next(check for check in diagnose().checks if check.name == DEVICE_CHECK)

    assert answer["detail"] == found.detail
    assert answer["connected"] is (found.status is CheckStatus.OK)


def test_only_the_commands_that_open_a_drive_are_marked() -> None:
    marked = {form.command for form in forms() if form.needs_hardware}

    assert marked == {"dump", "write", "surface"}


def test_a_command_whose_source_is_unreadable_is_marked_rather_than_cleared() -> None:
    def hidden() -> None:
        """A command installed without its source beside it."""

    with patch("fdstoolkit.ui.forms.inspect.getsource", side_effect=OSError):
        assert opens_a_drive(hidden)


def test_every_marked_commandopens_a_drive_in_the_cli() -> None:
    opens = {
        registered.name or registered.callback.__name__
        for registered in cli_app.registered_commands
        if registered.callback is not None
        and "open_drive(" in inspect.getsource(registered.callback)
    }

    assert {form.command for form in forms() if form.needs_hardware} == opens


def packed_capture() -> str:
    return base64.b64encode(pack_raw03(bytes([0] * 700 + [1] * 200 + [2] * 100))).decode("ascii")


def test_calibrate_converts_a_console_cycle_count(client: TestClient) -> None:
    body = client.post("/api/calibrate", json={"cycles": 152}).json()

    assert body["speed"]["bit_rate_hz"] == pytest.approx(94_200, rel=0.01)
    assert "raise the motor speed" in body["speed"]["advice"]
    assert "clockwise" not in body["speed"]["advice"]
    assert body["classes"] is None
    assert body["headline"] == "speed in spec"
    assert not body["ok"]


def test_calibrate_judges_a_capture(client: TestClient) -> None:
    body = client.post("/api/calibrate", json={"capture": packed_capture()}).json()

    assert len(body["classes"]["counts"]) == 4
    assert body["speed"] is None
    assert body["headline"].startswith("pulse classes ")


def test_calibrate_reports_both_measurements_together(client: TestClient) -> None:
    body = client.post("/api/calibrate", json={"cycles": 148, "capture": packed_capture()}).json()

    assert body["headline"].startswith("speed fine, pulse classes ")


def test_calibrate_needs_something_to_measure(client: TestClient) -> None:
    answer = client.post("/api/calibrate", json={})

    assert answer.status_code == UNPROCESSABLE
    assert "a cycle count, a capture, or both" in answer.json()["detail"]


def test_calibrate_refuses_a_cycle_count_of_nothing(client: TestClient) -> None:
    answer = client.post("/api/calibrate", json={"cycles": 0})

    assert answer.status_code == UNPROCESSABLE


def test_calibrate_refuses_a_capture_that_carries_nothing(client: TestClient) -> None:
    answer = client.post("/api/calibrate", json={"capture": ""})

    assert answer.status_code == BAD_REQUEST
    assert "carries no bytes" in answer.json()["detail"]


def test_status_reports_only_the_device_checks(client: TestClient) -> None:
    body = client.get("/api/status").json()

    names = {check["name"] for check in body["checks"]}
    assert "fdsstick" in names
    assert "python" not in names
    assert isinstance(body["healthy"], bool)
