from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from app_kit import BAD_REQUEST, ENCODED, IMAGE, OK, UNPROCESSABLE
from typer.testing import CliRunner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app as cli_app
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.diskinfo import PROFILES
from fdstoolkit.identify.hashes import digests_of

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


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


def test_hash_offers_the_canonical_image_the_command_writes(
    client: TestClient, tmp_path: Path
) -> None:
    # Arrange
    stamped = bytearray(IMAGE)
    stamped[0x31:0x33] = b"\x12\x34"
    (tmp_path / "disk.fds").write_bytes(stamped)
    command = ["hash", str(tmp_path / "disk.fds"), "--profile", "release", "-o"]
    CliRunner().invoke(cli_app, [*command, str(tmp_path / "canonical.fds")])
    encoded = base64.b64encode(bytes(stamped)).decode("ascii")
    payload = {"data": encoded, "profile": "release", "canonical_image": True}

    # Act
    body = client.post("/api/hash", json=payload).json()

    # Assert
    assert base64.b64decode(body["file"]["data"]) == (tmp_path / "canonical.fds").read_bytes()
    assert body["file"]["name"] == "disk.release.fds"


def test_hash_offers_no_image_unless_asked(client: TestClient) -> None:
    # Arrange
    expected = None

    # Act
    body = client.post("/api/hash", json={"data": ENCODED}).json()

    # Assert
    assert body["file"] is expected
