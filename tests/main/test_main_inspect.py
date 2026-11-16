from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from main_kit import runner, written_side_captures

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app
from fdstoolkit.core.disk import SIDE_SIZE

if TYPE_CHECKING:
    import pytest


def test_info_reports_each_side(image: Path) -> None:
    # Arrange
    arguments = ["info", str(image)]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    assert "SMB" in result.stdout
    assert "side 1" in result.stdout


def test_info_as_json_is_machine_readable(image: Path) -> None:
    # Arrange
    result = runner.invoke(app, ["info", str(image), "--json"])

    # Act
    payload = json.loads(result.stdout)

    # Assert
    assert payload["sides"][0]["game_name"] == "SMB"
    assert payload["side_count"] == 2


def test_json_output_has_no_timestamp(image: Path) -> None:
    # Arrange
    arguments = ["info", str(image), "--json"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    payload = json.loads(result.stdout)
    assert "timestamp" not in payload
    assert "generated_at" not in payload


def test_info_lists_files(tmp_path: Path) -> None:
    # Arrange
    source = tmp_path / "with-file.fds"
    content = bytearray(blank_image(sides=1, headered=False, formatted=True))
    content[56:58] = bytes([0x02, 0x01])
    header = (
        bytes([0x03, 0x00, 0x00])
        + b"KYODAKU-"
        + (0x6000).to_bytes(2, "little")
        + (4).to_bytes(2, "little")
        + bytes([0x00])
    )
    content[58 : 58 + len(header)] = header
    content[58 + len(header) : 58 + len(header) + 5] = bytes([0x04]) + bytes(4)
    source.write_bytes(bytes(content))

    # Act
    result = runner.invoke(app, ["info", str(source), "--files"])

    # Assert
    assert result.exit_code == 0
    assert "KYODAKU-" in result.stdout


def test_verify_passes_on_a_clean_image(image: Path) -> None:
    # Arrange
    arguments = ["verify", str(image)]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0


def test_verify_fails_on_an_error(damaged: Path) -> None:
    # Arrange
    arguments = ["verify", str(damaged)]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 1
    assert "FDS008" in result.stdout


def test_verify_in_strict_mode_fails_on_a_warning(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "unformatted.fds"

    # Act
    path.write_bytes(bytes(SIDE_SIZE))

    # Assert
    assert runner.invoke(app, ["verify", str(path)]).exit_code == 0
    assert runner.invoke(app, ["verify", str(path), "--strict"]).exit_code == 1


def test_hash_reports_every_algorithm(image: Path) -> None:
    # Arrange
    expected = {"size", "crc32", "md5", "sha1", "sha256"}

    # Act
    payload = json.loads(runner.invoke(app, ["hash", str(image), "--json"]).stdout)

    # Assert
    assert set(payload["image"]) == expected
    assert len(payload["sides"]) == 2
    assert payload["canonical"].startswith("fdstoolkit:v1:content/v1:")


def test_hash_writes_the_canonical_image(image: Path, tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "canon.fds"

    # Act
    result = runner.invoke(app, ["hash", str(image), "-o", str(out)])

    # Assert
    assert result.exit_code == 0
    assert out.stat().st_size == 2 * SIDE_SIZE
    assert "fdstoolkit:v1:content/v1:" in result.stdout
    assert f"wrote {out}" in result.stdout


def test_hash_refuses_to_overwrite_the_canonical_image(image: Path, tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "canon.fds"
    out.write_bytes(b"x")

    # Act
    result = runner.invoke(app, ["hash", str(image), "-o", str(out)])

    # Assert
    assert result.exit_code == 1
    assert out.read_bytes() == b"x"


def test_hash_accepts_a_profile(image: Path) -> None:
    # Arrange
    arguments = ["hash", str(image), "--profile", "data"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    assert "data/v1" in result.stdout


def test_provenance_reports_each_side(image: Path) -> None:
    # Arrange
    arguments = ["provenance", str(image)]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    assert "factory" in result.stdout


def test_provenance_as_json_lists_every_side(image: Path) -> None:
    # Arrange
    expected = 2

    # Act
    payload = json.loads(runner.invoke(app, ["provenance", str(image), "--json"]).stdout)

    # Assert
    assert len(payload["sides"]) == expected
    assert payload["sides"][0]["origin"] == "factory"


def test_info_prints_its_findings(damaged: Path) -> None:
    # Arrange
    arguments = ["info", str(damaged)]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert "FDS008" in result.stdout


def test_info_lists_files_as_json(hidden_file_image: Path) -> None:
    # Arrange
    expected = "SECRET"

    # Act
    payload = json.loads(
        runner.invoke(app, ["info", str(hidden_file_image), "--files", "--json"]).stdout
    )

    # Assert
    assert payload["files"][0]["name"] == expected
    assert payload["files"][0]["hidden"] is True


def test_info_marks_a_hidden_file(hidden_file_image: Path) -> None:
    # Arrange
    arguments = ["info", str(hidden_file_image), "--files"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert "(hidden)" in result.stdout


def test_verify_can_emit_json(image: Path) -> None:
    # Arrange
    expected = True

    # Act
    payload = json.loads(runner.invoke(app, ["verify", str(image), "--json"]).stdout)

    # Assert
    assert payload["ok"] is expected
    assert payload["worst_severity"] == "info"


def test_hash_prints_a_human_report(image: Path) -> None:
    # Arrange
    arguments = ["hash", str(image)]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert "sha256" in result.stdout
    assert "canonical fdstoolkit:v1:content/v1:" in result.stdout


def test_hash_rejects_an_unknown_profile(image: Path) -> None:
    # Arrange
    arguments = ["hash", str(image), "--profile", "nope"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 1
    assert "unknown profile" in result.stdout


def test_provenance_prints_its_notes(tmp_path: Path) -> None:
    # Arrange
    raw = bytearray(blank_image(sides=1, headered=False, formatted=True))
    raw[0x34] = 0xAF
    path = tmp_path / "odd.fds"
    path.write_bytes(bytes(raw))

    # Act
    result = runner.invoke(app, ["provenance", str(path)])

    # Assert
    assert "rewrite count" in result.stdout


def test_boot_reports_a_side_that_needs_a_bypass(single_side: Path) -> None:
    # Arrange
    arguments = ["boot", str(single_side)]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    assert "BIOS error 20" in result.stdout


def test_boot_fails_an_unformatted_first_side(tmp_path: Path) -> None:
    # Arrange
    source = tmp_path / "blank.fds"
    source.write_bytes(blank_image(sides=1, headered=False, formatted=False))

    # Act
    result = runner.invoke(app, ["boot", str(source)])

    # Assert
    assert result.exit_code == 1
    assert "block 1 expected" in result.stdout


def test_boot_lists_the_files_it_loads(tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "approval.bin"
    payload.write_bytes(bytes(224))
    source = tmp_path / "one.fds"
    source.write_bytes(blank_image(sides=1, headered=False, formatted=True))
    built = tmp_path / "built.fds"
    runner.invoke(
        app,
        [
            "insert",
            str(source),
            "-o",
            str(built),
            "--file",
            str(payload),
            "--name",
            "KYODAKU-",
            "--address",
            "2800",
            "--kind",
            "nametable",
        ],
    )

    # Act
    result = runner.invoke(app, ["boot", str(built)])

    # Assert
    assert "boots" in result.stdout
    assert "at $2800" in result.stdout


def test_boot_can_emit_json(single_side: Path) -> None:
    # Arrange
    expected = "needs_bypass"

    # Act
    payload = json.loads(runner.invoke(app, ["boot", str(single_side), "--json"]).stdout)

    # Assert
    assert payload["sides"][0]["verdict"] == expected
    assert payload["sides"][0]["error"] == 0x20


def test_doctor_reports_the_installation() -> None:
    # Arrange
    arguments = ["doctor"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    assert "fdstoolkit" in result.stdout
    assert "dat cache" not in result.stdout


def test_doctor_can_emit_json() -> None:
    # Arrange
    expected = True

    # Act
    payload = json.loads(runner.invoke(app, ["doctor", "--json"]).stdout)

    # Assert
    assert payload["healthy"] is expected
    assert {check["name"] for check in payload["checks"]} >= {"fdstoolkit", "python", "codec"}


def test_doctor_fails_on_an_unhealthy_installation(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    class RefusingHandle:
        def open_path(self, path: bytes) -> None:
            del path
            message = "Permission denied"
            raise PermissionError(message)

        def close(self) -> None:
            return None

    class RefusingHid:
        def device(self) -> RefusingHandle:
            return RefusingHandle()

        def enumerate(self, vendor_id: int, product_id: int) -> list[dict[str, object]]:
            return [{"vendor_id": vendor_id, "product_id": product_id, "path": b"usb:1"}]

    monkeypatch.setitem(sys.modules, "hid", RefusingHid())

    # Act
    result = runner.invoke(app, ["doctor"])

    # Assert
    assert result.exit_code == 1
    assert "[failed]" in result.stdout


def test_provenance_with_captures_names_a_side_the_fdsstick_wrote(tmp_path: Path) -> None:
    # Arrange
    image, captures = written_side_captures(tmp_path)

    # Act
    result = runner.invoke(app, ["provenance", str(image), "--captures", str(captures)])

    # Assert
    assert result.exit_code == 0
    assert "side 0: rewritten" in result.stdout
    assert "written in one stream" in result.stdout


def test_provenance_with_captures_reports_the_layout_as_json(tmp_path: Path) -> None:
    # Arrange
    image, captures = written_side_captures(tmp_path)

    # Act
    result = runner.invoke(app, ["provenance", str(image), "--captures", str(captures), "--json"])

    # Assert
    assert json.loads(result.stdout)["sides"][0]["layout"] == "streamed"


def test_provenance_refuses_captures_of_another_disk(tmp_path: Path) -> None:
    # Arrange
    _, captures = written_side_captures(tmp_path)
    other = tmp_path / "other.fds"
    other.write_bytes(blank_image(sides=1, headered=False, formatted=True))

    # Act
    result = runner.invoke(app, ["provenance", str(other), "--captures", str(captures)])

    # Assert
    assert result.exit_code == 1
    assert "another disk" in result.stdout
