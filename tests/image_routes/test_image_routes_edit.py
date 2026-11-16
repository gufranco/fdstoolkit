from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from recipe_fixture import recipe_text
from typer.testing import CliRunner

from fdstoolkit.build.calibration import calibration_disk
from fdstoolkit.cli.main import app as cli
from fdstoolkit.codecs import qd
from fdstoolkit.core.disk import Disk

if TYPE_CHECKING:
    from faker import Faker
    from fastapi.testclient import TestClient
from image_routes_kit import (
    BAD_REQUEST,
    GAME,
    OK,
    ONE,
    ONE_SIDE,
    OTHER_GAME,
    UNPROCESSABLE,
    ips_patch,
    zipped_folder,
)


def test_set_changes_a_disk_information_field(client: TestClient) -> None:
    # Arrange
    expected = len(ONE_SIDE)

    # Act
    body = client.post(
        "/api/set",
        json={"data": ONE, "edits": [f"game_name={OTHER_GAME}"]},
    ).json()

    # Assert
    assert body["size"] == expected


def test_an_edit_that_names_no_field_is_refused(client: TestClient) -> None:
    # Arrange
    route = "/api/set"
    payload = {"data": ONE, "edits": ["nonsense"]}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == BAD_REQUEST


def test_rebuild_reemits_the_image(client: TestClient) -> None:
    # Arrange
    expected = len(ONE_SIDE)

    # Act
    body = client.post("/api/rebuild", json={"data": ONE}).json()

    # Assert
    assert body["size"] == expected


def test_a_patch_that_is_not_a_patch_is_refused(client: TestClient) -> None:
    # Arrange
    rubbish = base64.b64encode(b"nonsense").decode("ascii")

    # Act
    answer = client.post("/api/patch", json={"data": ONE, "patch": rubbish})

    # Assert
    assert answer.status_code == BAD_REQUEST


def test_a_save_that_does_not_apply_is_refused(client: TestClient) -> None:
    # Arrange
    rubbish = base64.b64encode(b"nonsense").decode("ascii")

    # Act
    answer = client.post("/api/save", json={"action": "apply", "images": [ONE], "save": rubbish})

    # Assert
    assert answer.status_code == BAD_REQUEST


def test_save_extract_reports_the_difference(client: TestClient) -> None:
    # Arrange
    payload = {"action": "extract", "images": [ONE], "played": ONE, "save_as": "ips"}

    # Act
    body = client.post("/api/save", json=payload).json()

    # Assert
    assert body["name"].endswith(".ips")


def test_an_unknown_save_format_is_refused(client: TestClient) -> None:
    # Arrange
    route = "/api/save"
    payload = {"action": "extract", "images": [ONE], "played": ONE, "save_as": "nonsense"}

    # Act
    answer = client.post(
        route,
        json=payload,
    )

    # Assert
    assert answer.status_code == BAD_REQUEST


def test_a_recipe_file_that_does_not_parse_is_refused(client: TestClient) -> None:
    # Arrange
    rubbish = base64.b64encode(b"[]").decode("ascii")

    # Act
    answer = client.post("/api/save", json={"action": "blank", "images": [ONE], "recipes": rubbish})

    # Assert
    assert answer.status_code == BAD_REQUEST


def test_a_manifest_that_does_not_parse_is_refused(client: TestClient) -> None:
    # Arrange
    rubbish = base64.b64encode(b"{").decode("ascii")

    # Act
    answer = client.post("/api/build", json={"manifest": rubbish})

    # Assert
    assert answer.status_code == BAD_REQUEST


def test_a_patch_that_applies_produces_a_file(client: TestClient) -> None:
    # Arrange
    changed = bytearray(ONE_SIDE)
    changed[60] ^= 0xFF
    payload = base64.b64encode(ips_patch(ONE_SIDE, bytes(changed))).decode("ascii")

    # Act
    body = client.post("/api/patch", json={"data": ONE, "patch": payload}).json()

    # Assert
    assert body["size"] == len(ONE_SIDE)


def test_a_save_that_applies_produces_a_file(client: TestClient) -> None:
    # Arrange
    changed = bytearray(ONE_SIDE)
    changed[70] ^= 0xFF
    payload = base64.b64encode(ips_patch(ONE_SIDE, bytes(changed))).decode("ascii")

    # Act
    body = client.post(
        "/api/save", json={"action": "apply", "images": [ONE], "save": payload}
    ).json()

    # Assert
    assert body["size"] == len(ONE_SIDE)


def test_a_recipe_file_that_parses_normalises_the_save(client: TestClient) -> None:
    # Arrange
    recipes = base64.b64encode(
        recipe_text(game_name=GAME, source="measured against two dumps").encode()
    ).decode("ascii")
    payload = base64.b64encode(b"\x00" * 64).decode("ascii")
    with_file = client.post(
        "/api/insert",
        json={"data": ONE, "file": payload, "file_name": "SAVEDATA"},
    ).json()

    # Act
    body = client.post(
        "/api/save",
        json={"action": "blank", "images": [with_file["data"]], "recipes": recipes},
    ).json()

    # Assert
    assert body["size"] == len(ONE_SIDE)


def test_a_recipe_that_names_a_file_that_is_not_there_is_refused(
    client: TestClient,
) -> None:
    # Arrange
    recipes = base64.b64encode(
        json.dumps(
            {
                "version": 1,
                "recipes": [
                    {
                        "game_name": GAME,
                        "game_version": 0,
                        "side": 0,
                        "position": 9,
                        "fill": 0,
                        "source": "measured against two dumps",
                    }
                ],
            }
        ).encode()
    ).decode("ascii")

    # Act
    answer = client.post("/api/save", json={"action": "blank", "images": [ONE], "recipes": recipes})

    # Assert
    assert answer.status_code == BAD_REQUEST


def test_a_manifest_that_parses_builds_an_image(client: TestClient) -> None:
    # Arrange
    manifest = base64.b64encode(
        json.dumps({"sides": [{"game_name": GAME, "files": []}]}).encode()
    ).decode("ascii")

    # Act
    answer = client.post("/api/build", json={"manifest": manifest})

    # Assert
    assert answer.status_code == OK


def test_a_manifest_naming_a_file_on_this_machine_is_refused(
    client: TestClient, tmp_path: Path, fake: Faker
) -> None:
    # Arrange
    outside = tmp_path / fake.file_name()
    outside.write_bytes(fake.binary(length=32))
    side = {"files": [{"name": "X", "path": str(outside)}]}
    manifest = base64.b64encode(json.dumps({"sides": [side]}).encode()).decode("ascii")

    # Act
    answer = client.post("/api/build", json={"manifest": manifest})

    # Assert
    assert answer.status_code == BAD_REQUEST
    assert answer.json()["detail"] == (
        f"side 1 file 1: {outside} lies outside the uploaded folder, so it is not read"
    )


def test_a_zipped_manifest_builds_what_the_command_builds(
    client: TestClient, tmp_path: Path, fake: Faker
) -> None:
    # Arrange
    side = {"files": [{"name": "X", "path": "x.prg"}]}
    folder = zipped_folder(
        {"disk.json": json.dumps({"sides": [side]}).encode(), "x.prg": fake.binary(length=64)}
    )
    (tmp_path / "disk.zip").write_bytes(folder)
    CliRunner().invoke(cli, ["build", str(tmp_path / "disk.zip"), "-o", str(tmp_path / "x.fds")])
    upload = base64.b64encode(folder).decode("ascii")

    # Act
    answer = client.post("/api/build", json={"manifest": upload})

    # Assert
    assert base64.b64decode(answer.json()["data"]) == (tmp_path / "x.fds").read_bytes()


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"action": "apply", "images": [ONE]}, "save apply needs a save"),
        ({"action": "extract", "images": [ONE]}, "save extract needs the played image"),
        ({"action": "blank", "images": [ONE]}, "save blank needs a recipe file"),
        ({"action": "apply", "images": [ONE, ONE], "save": ONE}, "save apply works on one image"),
    ],
)
def test_a_save_action_missing_what_it_needs_is_refused(
    client: TestClient, payload: dict[str, object], detail: str
) -> None:
    # Arrange
    route = "/api/save"

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == UNPROCESSABLE
    assert answer.json()["detail"] == detail


def test_a_save_action_it_does_not_know_is_refused(client: TestClient) -> None:
    # Arrange
    route = "/api/save"
    payload = {"action": "erase", "images": [ONE]}

    # Act
    answer = client.post(route, json=payload)

    # Assert
    assert answer.status_code == BAD_REQUEST


@pytest.mark.parametrize("sides", [1, 2])
def test_a_qd_upload_reads_as_the_command_reads_it(
    client: TestClient, tmp_path: Path, sides: int
) -> None:
    # Arrange
    image, _ = qd.encode(Disk(sides=calibration_disk().sides[:sides]))
    (tmp_path / "disk.qd").write_bytes(image)
    command = CliRunner().invoke(cli, ["info", str(tmp_path / "disk.qd"), "--files", "--json"])
    upload = base64.b64encode(image).decode("ascii")

    # Act
    answer = client.post("/api/info", json={"data": upload, "name": "disk.qd"})

    # Assert
    files = json.loads(command.output)["files"]
    assert [entry["name"] for entry in answer.json()["files"]] == [entry["name"] for entry in files]
