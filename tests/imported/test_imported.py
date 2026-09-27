from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from capture_fixture import loopy_raw, qdc_raw

from fdstoolkit.build.calibration import calibration_disk
from fdstoolkit.codecs.raw import decode_packed, encode_raw03
from fdstoolkit.drive.captures import BundleError, Capture, bundle_zip, write_bundle
from fdstoolkit.drive.imported import (
    IMPORTED,
    MAX_IMPORTED_BYTES,
    MAX_IMPORTED_FILES,
    bundle_from_bytes,
    bundle_from_path,
    imported_bundle,
)


def payloads(side: int) -> list[bytes]:
    return [block.payload for block in calibration_disk(2).sides[side].blocks]


def read_blocks(capture_data: bytes) -> list[bytes]:
    side, _ = decode_packed(capture_data)
    return [block.payload for block in side.blocks]


def test_a_loopy_raw_file_reads_as_a_capture_of_its_side() -> None:
    bundle = imported_bundle({"game-A.raw": loopy_raw()})

    assert [(capture.side, capture.read) for capture in bundle.captures] == [(0, 1)]
    assert read_blocks(bundle.captures[0].data) == payloads(0)


def test_a_qdc_raw_file_reads_as_a_capture_of_its_side() -> None:
    bundle = imported_bundle({"game-B.raw": qdc_raw(1)})

    assert [(capture.side, capture.read) for capture in bundle.captures] == [(1, 1)]
    assert read_blocks(bundle.captures[0].data) == payloads(1)


def test_repeated_reads_of_one_side_are_numbered_in_name_order() -> None:
    bundle = imported_bundle(
        {"b-A.raw": loopy_raw(), "a-A.raw": loopy_raw(), "c-B.raw": qdc_raw(1)}
    )

    assert [(capture.side, capture.read) for capture in bundle.captures] == [(0, 1), (0, 2), (1, 1)]


def test_a_file_without_a_side_letter_is_side_a() -> None:
    bundle = imported_bundle({"game.raw": loopy_raw()})

    assert bundle.captures[0].side == 0


def test_a_side_letter_past_b_is_refused_with_its_name() -> None:
    with pytest.raises(BundleError, match=r"game-C\.raw names side C"):
        imported_bundle({"game-C.raw": loopy_raw()})


def test_a_file_that_is_neither_format_is_refused_with_its_name() -> None:
    with pytest.raises(BundleError, match=r"notes\.txt is neither a capture bundle"):
        imported_bundle({"notes.txt": b"hello"})


def test_no_file_at_all_is_refused() -> None:
    with pytest.raises(BundleError, match=r"no manifest\.json and no capture file"):
        imported_bundle({})


def zipped(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_a_zip_of_raw_files_without_a_manifest_is_imported() -> None:
    bundle = bundle_from_bytes(zipped({"game-A.raw": loopy_raw(), "game-B.raw": qdc_raw(1)}))

    assert bundle.image == IMPORTED
    assert [capture.side for capture in bundle.captures] == [0, 1]


def test_a_zip_with_a_manifest_is_read_as_a_bundle() -> None:
    packed = encode_raw03(calibration_disk(1), side=0)
    data = bundle_zip([Capture(side=0, read=1, data=packed)], image="cal.fds", created="now")

    bundle = bundle_from_bytes(data)

    assert bundle.image == "cal.fds"


def test_a_single_raw_file_uploaded_on_its_own_is_imported() -> None:
    bundle = bundle_from_bytes(loopy_raw())

    assert [(capture.side, capture.read) for capture in bundle.captures] == [(0, 1)]


def test_a_directory_of_raw_files_is_imported(tmp_path: Path) -> None:
    (tmp_path / "game-A.raw").write_bytes(loopy_raw())
    (tmp_path / "game-B.raw").write_bytes(qdc_raw(1))

    bundle = bundle_from_path(tmp_path)

    assert [capture.side for capture in bundle.captures] == [0, 1]


def test_a_directory_with_a_manifest_is_read_as_a_bundle(tmp_path: Path) -> None:
    packed = encode_raw03(calibration_disk(1), side=0)
    write_bundle(tmp_path, [Capture(side=0, read=1, data=packed)], image="cal.fds", created="now")

    bundle = bundle_from_path(tmp_path)

    assert bundle.image == "cal.fds"


def test_one_raw_file_named_on_the_command_line_is_imported(tmp_path: Path) -> None:
    path = tmp_path / "game-B.raw"
    path.write_bytes(qdc_raw(1))

    bundle = bundle_from_path(path)

    assert [capture.side for capture in bundle.captures] == [1]


def test_a_zip_named_on_the_command_line_is_opened(tmp_path: Path) -> None:
    path = tmp_path / "captures.zip"
    path.write_bytes(zipped({"game-A.raw": loopy_raw()}))

    bundle = bundle_from_path(path)

    assert bundle.image == IMPORTED


def test_a_path_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    with pytest.raises(BundleError, match="neither"):
        bundle_from_path(tmp_path / "missing")


def test_a_damaged_qdc_file_is_refused_with_its_name() -> None:
    with pytest.raises(BundleError, match=r"cut-A\.raw: the QDC file ends inside"):
        imported_bundle({"cut-A.raw": bytes([0, 0, 0, 0, 0x20, 0x00, 0x01])})


def test_a_zip_holding_too_many_files_is_refused() -> None:
    files = {f"read{index:02d}-A.raw": b"\x00" for index in range(MAX_IMPORTED_FILES + 1)}

    with pytest.raises(BundleError, match="more files than"):
        bundle_from_bytes(zipped(files))


def test_a_file_in_a_directory_larger_than_any_side_is_refused(tmp_path: Path) -> None:
    (tmp_path / "huge-A.raw").write_bytes(bytes(MAX_IMPORTED_BYTES + 1))

    with pytest.raises(BundleError, match=r"huge-A\.raw is larger"):
        bundle_from_path(tmp_path)
