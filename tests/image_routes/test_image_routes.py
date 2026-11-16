from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from fdstoolkit.build.fdspacker import FdsPackerManifest
from fdstoolkit.cli.main import app as cli

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
from image_routes_kit import BAD_REQUEST, ENCODED, ONE, RENAMED, UNPROCESSABLE, written_side


def test_diff_reports_no_difference_between_one_image_and_itself(
    client: TestClient,
) -> None:
    # Arrange
    expected = []

    # Act
    body = client.post("/api/diff", json={"left": ENCODED, "right": ENCODED}).json()

    # Assert
    assert body["blocks"] == expected
    assert body["headline"] == "identical"
    assert body["ok"]


def test_diff_says_why_two_unlike_disks_cannot_be_compared_block_by_block(
    client: TestClient,
) -> None:
    # Arrange
    expected = []

    # Act
    body = client.post("/api/diff", json={"left": ENCODED, "right": ONE}).json()

    # Assert
    assert body["blocks"] == expected
    assert body["headline"] == "different disks: 2 side(s) against 1"
    assert not body["ok"]


def test_diff_counts_the_sides_when_not_asked_to_explain(client: TestClient) -> None:
    # Arrange
    expected = "side count differs: 2 against 1"

    # Act
    body = client.post(
        "/api/diff",
        json={"left": ENCODED, "right": ONE, "explain": False},
    ).json()

    # Assert
    assert body["headline"] == expected


def test_diff_names_the_block_that_differs(client: TestClient) -> None:
    # Arrange
    expected = [{"side": 0, "block": 0}, {"side": 1, "block": 0}]

    # Act
    body = client.post(
        "/api/diff",
        json={"left": ENCODED, "right": RENAMED, "explain": False},
    ).json()

    # Assert
    assert body["blocks"] == expected
    assert body["headline"] == "2 block(s) differ"


def test_diff_names_the_field_that_differs_without_being_asked(
    client: TestClient,
) -> None:
    # Arrange
    expected = ["game_name", "game_name"]

    # Act
    body = client.post("/api/diff", json={"left": ENCODED, "right": RENAMED}).json()

    # Assert
    assert [entry["field"] for entry in body["differences"]] == expected
    assert [entry["side"] for entry in body["differences"]] == [0, 1]
    assert body["same_software"] is False


def test_diff_reports_nothing_extra_when_explaining_is_turned_off(client: TestClient) -> None:
    # Arrange
    expected = []

    # Act
    body = client.post(
        "/api/diff",
        json={"left": ENCODED, "right": RENAMED, "explain": False},
    ).json()

    # Assert
    assert body["differences"] == expected
    assert body["file_changes"] == []


def test_boot_predicts_what_the_console_does(client: TestClient) -> None:
    # Arrange
    expected = 2

    # Act
    body = client.post("/api/boot", json={"data": ENCODED}).json()

    # Assert
    assert len(body["rows"]) == expected


def test_provenance_reports_a_verdict_per_side(client: TestClient) -> None:
    # Arrange
    expected = 2

    # Act
    body = client.post("/api/provenance", json={"data": ENCODED}).json()

    # Assert
    assert len(body["rows"]) == expected


def test_provenance_with_captures_names_a_side_the_fdsstick_wrote(client: TestClient) -> None:
    # Arrange
    image, captures = written_side()

    # Act
    body = client.post("/api/provenance", json={"data": image, "captures": captures}).json()

    # Assert
    assert body["rows"][0]["origin"] == "rewritten"
    assert body["rows"][0]["layout"] == "streamed"


def test_provenance_refuses_captures_of_another_disk(client: TestClient) -> None:
    # Arrange
    _, captures = written_side()

    # Act
    answer = client.post("/api/provenance", json={"data": ONE, "captures": captures})

    # Assert
    assert answer.status_code == UNPROCESSABLE
    assert "another disk" in answer.json()["detail"]


def test_save_find_compares_dumps_of_one_release(client: TestClient) -> None:
    # Arrange
    payload = {"action": "find", "images": [ENCODED, ENCODED]}

    # Act
    body = client.post("/api/save", json=payload).json()

    # Assert
    assert body["rows"] == []


def test_save_find_says_so_when_every_dump_agrees(client: TestClient) -> None:
    # Arrange
    expected = "no save candidate: every file agrees across the dumps"

    # Act
    body = client.post("/api/save", json={"action": "find", "images": [ENCODED, ENCODED]}).json()

    # Assert
    assert body["headline"] == expected


def test_save_find_needs_two_dumps(client: TestClient) -> None:
    # Arrange
    route = "/api/save"
    payload = {"action": "find", "images": [ENCODED]}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE


def test_extract_names_every_file_as_the_command_does(client: TestClient, tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "main.prg").write_bytes(bytes([0xEA]) * 32)
    side = {
        "game_name": "SMB",
        "file_amount": 1,
        "files": [{"file_name": "M/N", "data": "main.prg"}],
    }
    image = FdsPackerManifest.parse({"sides": [side]}, root=tmp_path).build()
    (tmp_path / "disk.fds").write_bytes(image)
    CliRunner().invoke(cli, ["extract", str(tmp_path / "disk.fds"), "-d", str(tmp_path / "out")])
    written = sorted(path.name for path in (tmp_path / "out").iterdir())

    # Act
    body = client.post("/api/extract", json={"data": base64.b64encode(image).decode()}).json()

    # Assert
    assert [entry["name"] for entry in body["files"]] == written
    assert written == ["side0-00-M_N.bin"]


def test_extract_can_add_an_fdspacker_manifest(client: TestClient, tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "main.prg").write_bytes(bytes([0xEA]) * 32)
    side = {
        "game_name": "SMB",
        "file_amount": 1,
        "files": [{"file_name": "MAIN", "data": "main.prg"}],
    }
    image = FdsPackerManifest.parse({"sides": [side]}, root=tmp_path).build()
    encoded = base64.b64encode(image).decode("ascii")

    # Act
    body = client.post("/api/extract", json={"data": encoded, "fdspacker": True}).json()

    # Assert
    assert [entry["name"] for entry in body["files"]] == ["diskinfo.json", "side0-00-MAIN.prg"]


def test_extract_says_why_a_disk_has_no_fdspacker_manifest(client: TestClient) -> None:
    # Arrange
    route = "/api/extract"
    payload = {"data": ENCODED, "fdspacker": True}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == BAD_REQUEST
    assert "rewritten_date" in answer.json()["detail"]


def test_insert_adds_a_file(client: TestClient) -> None:
    # Arrange
    payload = base64.b64encode(b"\x00" * 64).decode("ascii")

    # Act
    body = client.post(
        "/api/insert",
        json={"data": ONE, "file": payload, "file_name": "NEWFILE"},
    ).json()

    # Assert
    assert body["size"] > 0


def test_an_unknown_file_kind_is_refused(client: TestClient) -> None:
    # Arrange
    payload = base64.b64encode(b"\x00" * 8).decode("ascii")

    # Act
    answer = client.post(
        "/api/insert",
        json={"data": ONE, "file": payload, "file_name": "X", "kind": "nonsense"},
    )

    # Assert
    assert answer.status_code == BAD_REQUEST
