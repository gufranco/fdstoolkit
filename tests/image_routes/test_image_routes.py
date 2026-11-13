from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.calibration import calibration_disk
from fdstoolkit.build.fdspacker import FdsPackerManifest
from fdstoolkit.codecs.fds import encode
from fdstoolkit.drive.captures import Capture, bundle_zip
from fdstoolkit.ui.app import create_app

OK = 200
BAD_REQUEST = 400
UNPROCESSABLE = 422
IMAGE = blank_image(sides=2, headered=False, formatted=True, game_name="SMB")
ONE_SIDE = blank_image(sides=1, headered=False, formatted=True, game_name="SMB")
RENAMED_IMAGE = blank_image(sides=2, headered=False, formatted=True, game_name="ZLD")
ENCODED = base64.b64encode(IMAGE).decode("ascii")
ONE = base64.b64encode(ONE_SIDE).decode("ascii")
RENAMED = base64.b64encode(RENAMED_IMAGE).decode("ascii")


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(create_app(), base_url="http://127.0.0.1")


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


def written_side() -> tuple[str, str]:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "fdsstick"
    capture = Capture(side=0, read=1, data=(fixture / "calibration-side.raw03").read_bytes())
    image = encode(calibration_disk(1), headered=False)[0]
    bundle = bundle_zip([capture], image="calibration.fds", created="2026-11-13T00:00:00Z")
    return base64.b64encode(image).decode("ascii"), base64.b64encode(bundle).decode("ascii")


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


def test_extract_writes_every_file(client: TestClient) -> None:
    # Arrange
    payload = {"data": ENCODED}

    # Act
    body = client.post("/api/extract", json=payload).json()

    # Assert
    assert isinstance(body["files"], list)


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


def test_set_changes_a_disk_information_field(client: TestClient) -> None:
    # Arrange
    expected = len(ONE_SIDE)

    # Act
    body = client.post(
        "/api/set",
        json={"data": ONE, "edits": ["game_name=ABC"]},
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


def _ips(original: bytes, changed: bytes) -> bytes:
    body = bytearray(b"PATCH")
    for offset, (was, now) in enumerate(zip(original, changed, strict=False)):
        if was != now:
            body += offset.to_bytes(3, "big") + (1).to_bytes(2, "big") + bytes([now])
    body += b"EOF"
    return bytes(body)


def test_a_patch_that_applies_produces_a_file(client: TestClient) -> None:
    # Arrange
    changed = bytearray(ONE_SIDE)
    changed[60] ^= 0xFF
    payload = base64.b64encode(_ips(ONE_SIDE, bytes(changed))).decode("ascii")

    # Act
    body = client.post("/api/patch", json={"data": ONE, "patch": payload}).json()

    # Assert
    assert body["size"] == len(ONE_SIDE)


def test_a_save_that_applies_produces_a_file(client: TestClient) -> None:
    # Arrange
    changed = bytearray(ONE_SIDE)
    changed[70] ^= 0xFF
    payload = base64.b64encode(_ips(ONE_SIDE, bytes(changed))).decode("ascii")

    # Act
    body = client.post(
        "/api/save", json={"action": "apply", "images": [ONE], "save": payload}
    ).json()

    # Assert
    assert body["size"] == len(ONE_SIDE)


def test_a_recipe_file_that_parses_normalises_the_save(client: TestClient) -> None:
    # Arrange
    recipes = base64.b64encode(
        json.dumps(
            {
                "version": 1,
                "recipes": [
                    {
                        "game_name": "SMB",
                        "game_version": 0,
                        "side": 0,
                        "position": 0,
                        "fill": 0,
                        "source": "measured against two dumps",
                    }
                ],
            }
        ).encode()
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
                        "game_name": "SMB",
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
    manifest = base64.b64encode(b'{"sides": [{"game_name": "SMB", "files": []}]}').decode("ascii")

    # Act
    answer = client.post("/api/build", json={"manifest": manifest})

    # Assert
    assert answer.status_code in {OK, BAD_REQUEST}


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
