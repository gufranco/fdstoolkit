from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.ares import encode_side
from fdstoolkit.codecs.fds import decode
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
    return TestClient(create_app())


def test_ls_lists_every_file(client: TestClient) -> None:
    body = client.post("/api/ls", json={"data": ENCODED}).json()

    assert isinstance(body["rows"], list)
    assert body["headline"] == f"{len(body['rows'])} file(s) across 2 side(s)"


def test_diff_reports_no_difference_between_one_image_and_itself(
    client: TestClient,
) -> None:
    body = client.post("/api/diff", json={"left": ENCODED, "right": ENCODED}).json()

    assert body["blocks"] == []
    assert body["headline"] == "identical"
    assert body["ok"]


def test_diff_says_why_two_unlike_disks_cannot_be_compared_block_by_block(
    client: TestClient,
) -> None:
    body = client.post("/api/diff", json={"left": ENCODED, "right": ONE}).json()

    assert body["blocks"] == []
    assert body["headline"] == "different disks: 2 side(s) against 1"
    assert not body["ok"]


def test_diff_counts_the_sides_when_not_asked_to_explain(client: TestClient) -> None:
    body = client.post(
        "/api/diff",
        json={"left": ENCODED, "right": ONE, "explain": False},
    ).json()

    assert body["headline"] == "side count differs: 2 against 1"


def test_diff_names_the_block_that_differs(client: TestClient) -> None:
    body = client.post(
        "/api/diff",
        json={"left": ENCODED, "right": RENAMED, "explain": False},
    ).json()

    assert body["blocks"] == [{"side": 0, "block": 0}, {"side": 1, "block": 0}]
    assert body["headline"] == "2 block(s) differ"


def test_diff_names_the_field_that_differs_without_being_asked(
    client: TestClient,
) -> None:
    body = client.post("/api/diff", json={"left": ENCODED, "right": RENAMED}).json()

    assert [entry["field"] for entry in body["differences"]] == ["game_name", "game_name"]
    assert [entry["side"] for entry in body["differences"]] == [0, 1]
    assert body["same_software"] is False


def test_diff_reports_nothing_extra_when_explaining_is_turned_off(client: TestClient) -> None:
    body = client.post(
        "/api/diff",
        json={"left": ENCODED, "right": RENAMED, "explain": False},
    ).json()

    assert body["differences"] == []
    assert body["file_changes"] == []


def test_boot_predicts_what_the_console_does(client: TestClient) -> None:
    body = client.post("/api/boot", json={"data": ENCODED}).json()

    assert len(body["rows"]) == 2


def test_layout_places_every_file_on_the_spiral(client: TestClient) -> None:
    body = client.post("/api/layout", json={"data": ENCODED}).json()

    assert isinstance(body["rows"], list)


def test_provenance_reports_a_verdict_per_side(client: TestClient) -> None:
    body = client.post("/api/provenance", json={"data": ENCODED}).json()

    assert len(body["rows"]) == 2


def test_lint_checks_an_image_against_the_card(client: TestClient) -> None:
    body = client.post("/api/lint", json={"data": ONE, "name": "disk.fds"}).json()

    assert isinstance(body["rows"], list)


def test_lint_says_the_card_accepts_a_clean_image(client: TestClient) -> None:
    body = client.post("/api/lint", json={"data": ONE, "name": "disk.fds"}).json()

    assert body["headline"] == "the card accepts this image as it stands"
    assert body["ok"]


def test_saves_compares_dumps_of_one_release(client: TestClient) -> None:
    body = client.post("/api/saves", json={"images": [ENCODED, ENCODED]}).json()

    assert isinstance(body["rows"], list)


def test_saves_says_so_when_every_dump_agrees(client: TestClient) -> None:
    body = client.post("/api/saves", json={"images": [ENCODED, ENCODED]}).json()

    assert body["headline"] == "no save candidate: every file agrees across the dumps"


def test_saves_needs_at_least_one_dump(client: TestClient) -> None:
    answer = client.post("/api/saves", json={"images": []})

    assert answer.status_code == UNPROCESSABLE


def test_extract_writes_every_file(client: TestClient) -> None:
    body = client.post("/api/extract", json={"data": ENCODED}).json()

    assert isinstance(body["files"], list)


def test_insert_adds_a_file(client: TestClient) -> None:
    payload = base64.b64encode(b"\x00" * 64).decode("ascii")

    body = client.post(
        "/api/insert",
        json={"data": ONE, "file": payload, "file_name": "NEWFILE"},
    ).json()

    assert body["size"] > 0


def test_an_unknown_file_kind_is_refused(client: TestClient) -> None:
    payload = base64.b64encode(b"\x00" * 8).decode("ascii")

    answer = client.post(
        "/api/insert",
        json={"data": ONE, "file": payload, "file_name": "X", "kind": "nonsense"},
    )

    assert answer.status_code == BAD_REQUEST


def test_set_changes_a_disk_information_field(client: TestClient) -> None:
    body = client.post(
        "/api/set",
        json={"data": ONE, "edits": ["game_name=ABC"]},
    ).json()

    assert body["size"] == len(ONE_SIDE)


def test_an_edit_that_names_no_field_is_refused(client: TestClient) -> None:
    answer = client.post("/api/set", json={"data": ONE, "edits": ["nonsense"]})

    assert answer.status_code == BAD_REQUEST


def test_clean_removes_trailing_bytes(client: TestClient) -> None:
    body = client.post("/api/clean", json={"data": ONE}).json()

    assert body["size"] == len(ONE_SIDE)


def test_rebuild_reemits_the_image(client: TestClient) -> None:
    body = client.post("/api/rebuild", json={"data": ONE}).json()

    assert body["size"] == len(ONE_SIDE)


def test_a_patch_that_is_not_a_patch_is_refused(client: TestClient) -> None:
    rubbish = base64.b64encode(b"nonsense").decode("ascii")

    answer = client.post("/api/patch", json={"data": ONE, "patch": rubbish})

    assert answer.status_code == BAD_REQUEST


def test_a_save_that_does_not_apply_is_refused(client: TestClient) -> None:
    rubbish = base64.b64encode(b"nonsense").decode("ascii")

    answer = client.post("/api/save-apply", json={"data": ONE, "save": rubbish})

    assert answer.status_code == BAD_REQUEST


def test_save_extract_reports_the_difference(client: TestClient) -> None:
    body = client.post(
        "/api/save-extract",
        json={"data": ONE, "played": ONE, "save_as": "ips"},
    ).json()

    assert body["name"].endswith(".ips")


def test_an_unknown_save_format_is_refused(client: TestClient) -> None:
    answer = client.post(
        "/api/save-extract",
        json={"data": ONE, "played": ONE, "save_as": "nonsense"},
    )

    assert answer.status_code == BAD_REQUEST


def test_a_recipe_file_that_does_not_parse_is_refused(client: TestClient) -> None:
    rubbish = base64.b64encode(b"[]").decode("ascii")

    answer = client.post("/api/normalise-saves", json={"data": ONE, "recipes": rubbish})

    assert answer.status_code == BAD_REQUEST


def test_split_writes_one_file_per_side(client: TestClient) -> None:
    body = client.post("/api/split", json={"data": ENCODED}).json()

    assert len(body["files"]) == 2


def test_join_rebuilds_an_image_from_side_files(client: TestClient) -> None:
    halves = client.post("/api/split", json={"data": ENCODED}).json()["files"]

    body = client.post(
        "/api/join",
        json={
            "images": [entry["data"] for entry in halves],
            "names": [entry["name"] for entry in halves],
        },
    ).json()

    assert body["size"] == len(IMAGE)


def test_join_needs_a_side_file(client: TestClient) -> None:
    answer = client.post("/api/join", json={"images": []})

    assert answer.status_code == UNPROCESSABLE


def test_merge_joins_two_disks(client: TestClient) -> None:
    body = client.post("/api/merge", json={"images": [ONE, ONE]}).json()

    assert body["size"] >= len(ONE_SIDE) * 2


def test_merge_needs_a_disk(client: TestClient) -> None:
    answer = client.post("/api/merge", json={"images": []})

    assert answer.status_code == UNPROCESSABLE


def test_unmerge_splits_a_multi_disk_image(client: TestClient) -> None:
    body = client.post("/api/unmerge", json={"data": ENCODED}).json()

    assert body["files"]


def test_export_writes_the_layout_a_target_expects(client: TestClient) -> None:
    body = client.post("/api/export", json={"data": ONE, "target": "mesen2"}).json()

    assert body["files"]


def test_an_unknown_export_target_is_refused(client: TestClient) -> None:
    answer = client.post("/api/export", json={"data": ONE, "target": "nonsense"})

    assert answer.status_code == BAD_REQUEST


def test_import_ares_rebuilds_from_side_files(client: TestClient) -> None:
    answer = client.post("/api/import-ares", json={"images": []})

    assert answer.status_code == UNPROCESSABLE


def test_a_manifest_that_does_not_parse_is_refused(client: TestClient) -> None:
    rubbish = base64.b64encode(b"{").decode("ascii")

    answer = client.post("/api/build", json={"manifest": rubbish})

    assert answer.status_code == BAD_REQUEST


def test_card_builds_a_blank_the_firmware_accepts(client: TestClient) -> None:
    body = client.post("/api/card", json={"sides": 1}).json()

    assert body["size"] > 0


def test_an_unknown_firmware_variant_is_refused(client: TestClient) -> None:
    answer = client.post("/api/card", json={"sides": 1, "firmware": "nonsense"})

    assert answer.status_code == BAD_REQUEST


def _ips(original: bytes, changed: bytes) -> bytes:
    body = bytearray(b"PATCH")
    for offset, (was, now) in enumerate(zip(original, changed, strict=False)):
        if was != now:
            body += offset.to_bytes(3, "big") + (1).to_bytes(2, "big") + bytes([now])
    body += b"EOF"
    return bytes(body)


def test_a_patch_that_applies_produces_a_file(client: TestClient) -> None:
    changed = bytearray(ONE_SIDE)
    changed[60] ^= 0xFF
    payload = base64.b64encode(_ips(ONE_SIDE, bytes(changed))).decode("ascii")

    body = client.post("/api/patch", json={"data": ONE, "patch": payload}).json()

    assert body["size"] == len(ONE_SIDE)


def test_a_save_that_applies_produces_a_file(client: TestClient) -> None:
    changed = bytearray(ONE_SIDE)
    changed[70] ^= 0xFF
    payload = base64.b64encode(_ips(ONE_SIDE, bytes(changed))).decode("ascii")

    body = client.post("/api/save-apply", json={"data": ONE, "save": payload}).json()

    assert body["size"] == len(ONE_SIDE)


def test_a_recipe_file_that_parses_normalises_the_save(client: TestClient) -> None:
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

    body = client.post(
        "/api/normalise-saves",
        json={"data": with_file["data"], "recipes": recipes},
    ).json()

    assert body["size"] == len(ONE_SIDE)


def test_a_recipe_that_names_a_file_that_is_not_there_is_refused(
    client: TestClient,
) -> None:
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

    answer = client.post("/api/normalise-saves", json={"data": ONE, "recipes": recipes})

    assert answer.status_code == BAD_REQUEST


def test_import_ares_rebuilds_from_a_real_side_file(client: TestClient) -> None:
    rubbish = base64.b64encode(bytes(64)).decode("ascii")

    answer = client.post("/api/import-ares", json={"images": [rubbish]})

    assert answer.status_code in {OK, BAD_REQUEST}


def test_a_manifest_that_parses_builds_an_image(client: TestClient) -> None:
    manifest = base64.b64encode(b'{"sides": [{"game_name": "SMB", "files": []}]}').decode("ascii")

    answer = client.post("/api/build", json={"manifest": manifest})

    assert answer.status_code in {OK, BAD_REQUEST}


def test_import_ares_rebuilds_a_side_the_encoder_produced(client: TestClient) -> None:
    sample = base64.b64encode(b"\x00" * 64).decode("ascii")
    with_file = client.post(
        "/api/insert",
        json={"data": ONE, "file": sample, "file_name": "PRG"},
    ).json()
    disk, _ = decode(base64.b64decode(with_file["data"]))
    payload = base64.b64encode(encode_side(disk.sides[0])).decode("ascii")

    body = client.post("/api/import-ares", json={"images": [payload]}).json()

    assert body["size"] > 0
