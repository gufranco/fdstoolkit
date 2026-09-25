from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

import pytest

from fdstoolkit.drive.captures import (
    MANIFEST,
    MAX_CAPTURE_BYTES,
    BundleError,
    Capture,
    bundle_zip,
    created_now,
    load_bundle,
    read_zip,
    write_bundle,
)

CREATED = "2026-09-25T12:00:00Z"
CAPTURES = (
    Capture(side=0, read=1, data=b"\x01\x02\x03"),
    Capture(side=0, read=2, data=b"\x01\x02\x04"),
    Capture(side=1, read=1, data=b"\x05"),
)


def test_a_bundle_written_to_a_directory_reads_back_the_same(tmp_path: Path) -> None:
    written = write_bundle(tmp_path, CAPTURES, image="game.fds", created=CREATED)

    bundle = load_bundle(tmp_path)

    assert tmp_path / MANIFEST in written
    assert bundle.captures == CAPTURES
    assert bundle.image == "game.fds"
    assert bundle.created == CREATED
    assert bundle.of_side(0) == (b"\x01\x02\x03", b"\x01\x02\x04")
    assert bundle.sides == (0, 1)


def test_the_manifest_names_every_capture_with_its_digest(tmp_path: Path) -> None:
    write_bundle(tmp_path, CAPTURES, image="game.fds", created=CREATED)

    manifest = json.loads((tmp_path / MANIFEST).read_text(encoding="utf-8"))

    assert manifest["format"] == "fdstoolkit-captures"
    assert [entry["file"] for entry in manifest["captures"]] == [
        "side0.read01.raw03",
        "side0.read02.raw03",
        "side1.read01.raw03",
    ]
    assert all(len(entry["sha256"]) == 64 for entry in manifest["captures"])


def test_a_zip_bundle_reads_back_the_same(tmp_path: Path) -> None:
    archive = tmp_path / "captures.zip"
    archive.write_bytes(bundle_zip(CAPTURES, image="game.fds", created=CREATED))

    assert load_bundle(archive).captures == CAPTURES
    assert read_zip(archive.read_bytes()).captures == CAPTURES


def test_a_capture_that_changed_since_it_was_kept_is_refused(tmp_path: Path) -> None:
    write_bundle(tmp_path, CAPTURES, image="game.fds", created=CREATED)
    (tmp_path / "side0.read01.raw03").write_bytes(b"tampered")

    with pytest.raises(BundleError, match=r"side0\.read01\.raw03 does not match its digest"):
        load_bundle(tmp_path)


def test_a_capture_the_manifest_names_but_is_gone_is_refused(tmp_path: Path) -> None:
    write_bundle(tmp_path, CAPTURES, image="game.fds", created=CREATED)
    (tmp_path / "side1.read01.raw03").unlink()

    with pytest.raises(BundleError, match=r"side1\.read01\.raw03 is missing"):
        load_bundle(tmp_path)


def test_a_directory_without_a_manifest_is_refused(tmp_path: Path) -> None:
    (tmp_path / "loose.raw03").write_bytes(b"\x00")

    with pytest.raises(BundleError, match=r"no manifest\.json"):
        load_bundle(tmp_path)


def test_a_path_that_is_neither_a_directory_nor_a_zip_is_refused(tmp_path: Path) -> None:
    with pytest.raises(BundleError, match="neither a capture directory nor a zip"):
        load_bundle(tmp_path / "nothing.zip")


def test_bytes_that_are_not_a_zip_are_refused() -> None:
    with pytest.raises(BundleError, match="not a zip archive"):
        read_zip(b"not a zip")


def test_a_manifest_of_another_format_is_refused(tmp_path: Path) -> None:
    (tmp_path / MANIFEST).write_text(json.dumps({"format": "other", "version": 1}), "utf-8")

    with pytest.raises(BundleError, match="not a capture manifest"):
        load_bundle(tmp_path)


def test_a_manifest_that_is_not_json_is_refused(tmp_path: Path) -> None:
    (tmp_path / MANIFEST).write_text("{", "utf-8")

    with pytest.raises(BundleError, match="does not parse"):
        load_bundle(tmp_path)


def test_a_manifest_entry_with_an_impossible_side_is_refused(tmp_path: Path) -> None:
    write_bundle(tmp_path, CAPTURES, image="game.fds", created=CREATED)
    manifest = json.loads((tmp_path / MANIFEST).read_text(encoding="utf-8"))
    manifest["captures"][0]["side"] = 7
    (tmp_path / MANIFEST).write_text(json.dumps(manifest), "utf-8")

    with pytest.raises(BundleError, match="names side 7"):
        load_bundle(tmp_path)


def test_a_manifest_entry_missing_a_field_is_refused(tmp_path: Path) -> None:
    write_bundle(tmp_path, CAPTURES, image="game.fds", created=CREATED)
    manifest = json.loads((tmp_path / MANIFEST).read_text(encoding="utf-8"))
    del manifest["captures"][0]["sha256"]
    (tmp_path / MANIFEST).write_text(json.dumps(manifest), "utf-8")

    with pytest.raises(BundleError, match="does not describe a capture"):
        load_bundle(tmp_path)


def test_a_zip_member_larger_than_any_capture_is_refused() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            MANIFEST,
            json.dumps(
                {
                    "format": "fdstoolkit-captures",
                    "version": 1,
                    "tool": "x",
                    "created": CREATED,
                    "image": "g.fds",
                    "captures": [
                        {"file": "big.raw03", "side": 0, "read": 1, "size": 1, "sha256": "0" * 64}
                    ],
                }
            ),
        )
        archive.writestr("big.raw03", bytes(MAX_CAPTURE_BYTES + 1))

    with pytest.raises(BundleError, match=r"big\.raw03 is larger than any capture"):
        read_zip(buffer.getvalue())


def test_a_manifest_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    (tmp_path / MANIFEST).write_text("[]", "utf-8")

    with pytest.raises(BundleError, match="not a capture manifest"):
        load_bundle(tmp_path)


def test_a_manifest_whose_captures_are_not_a_list_is_refused(tmp_path: Path) -> None:
    write_bundle(tmp_path, CAPTURES, image="game.fds", created=CREATED)
    manifest = json.loads((tmp_path / MANIFEST).read_text(encoding="utf-8"))
    manifest["captures"] = "side0.read01.raw03"
    (tmp_path / MANIFEST).write_text(json.dumps(manifest), "utf-8")

    with pytest.raises(BundleError, match="does not list its captures"):
        load_bundle(tmp_path)


def test_a_manifest_entry_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    write_bundle(tmp_path, CAPTURES, image="game.fds", created=CREATED)
    manifest = json.loads((tmp_path / MANIFEST).read_text(encoding="utf-8"))
    manifest["captures"][0] = "side0.read01.raw03"
    (tmp_path / MANIFEST).write_text(json.dumps(manifest), "utf-8")

    with pytest.raises(BundleError, match="does not describe a capture"):
        load_bundle(tmp_path)


def test_a_zip_missing_a_listed_capture_is_refused() -> None:
    whole = zipfile.ZipFile(io.BytesIO(bundle_zip(CAPTURES, image="game.fds", created=CREATED)))
    buffer = io.BytesIO()
    with whole, zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(MANIFEST, whole.read(MANIFEST))

    with pytest.raises(BundleError, match=r"side0\.read01\.raw03 is missing"):
        read_zip(buffer.getvalue())


def test_a_bundle_is_stamped_in_utc_to_the_second() -> None:
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", created_now())
