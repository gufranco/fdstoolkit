from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fdstk.build.blank import blank_image
from fdstk.cli.main import app
from fdstk.codecs.fds import SIDE_SIZE

runner = CliRunner()


@pytest.fixture
def image(tmp_path: Path) -> Path:
    path = tmp_path / "disk.fds"
    path.write_bytes(blank_image(sides=2, headered=False, formatted=True, game_name="SMB"))
    return path


@pytest.fixture
def single_side(tmp_path: Path) -> Path:
    path = tmp_path / "one-side.fds"
    path.write_bytes(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    return path


@pytest.fixture
def damaged(tmp_path: Path) -> Path:
    raw = bytearray(blank_image(sides=1, headered=False, formatted=True))
    raw[1:15] = b"*NOT-NINTENDO*"
    path = tmp_path / "damaged.fds"
    path.write_bytes(bytes(raw))
    return path


def test_info_reports_each_side(image: Path) -> None:
    result = runner.invoke(app, ["info", str(image)])

    assert result.exit_code == 0
    assert "SMB" in result.stdout
    assert "side 1" in result.stdout


def test_info_as_json_is_machine_readable(image: Path) -> None:
    result = runner.invoke(app, ["info", str(image), "--json"])

    payload = json.loads(result.stdout)
    assert payload["sides"][0]["game_name"] == "SMB"
    assert payload["side_count"] == 2


def test_json_output_has_no_timestamp(image: Path) -> None:
    payload = json.loads(runner.invoke(app, ["info", str(image), "--json"]).stdout)

    assert "timestamp" not in payload
    assert "generated_at" not in payload


def test_ls_lists_files(tmp_path: Path) -> None:
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

    result = runner.invoke(app, ["ls", str(source)])

    assert result.exit_code == 0
    assert "KYODAKU-" in result.stdout


def test_verify_passes_on_a_clean_image(image: Path) -> None:
    result = runner.invoke(app, ["verify", str(image)])

    assert result.exit_code == 0


def test_verify_fails_on_an_error(damaged: Path) -> None:
    result = runner.invoke(app, ["verify", str(damaged)])

    assert result.exit_code == 1
    assert "FDS008" in result.stdout


def test_verify_in_strict_mode_fails_on_a_warning(tmp_path: Path) -> None:
    path = tmp_path / "unformatted.fds"
    path.write_bytes(bytes(SIDE_SIZE))

    assert runner.invoke(app, ["verify", str(path)]).exit_code == 0
    assert runner.invoke(app, ["verify", str(path), "--strict"]).exit_code == 1


def test_hash_reports_every_algorithm(image: Path) -> None:
    payload = json.loads(runner.invoke(app, ["hash", str(image), "--json"]).stdout)

    assert set(payload["image"]) == {"size", "crc32", "md5", "sha1", "sha256"}
    assert len(payload["sides"]) == 2
    assert payload["canonical"].startswith("fdscanon:v1:content/v1:")


def test_convert_writes_a_qd(image: Path, tmp_path: Path) -> None:
    out = tmp_path / "disk.qd"

    result = runner.invoke(app, ["convert", str(image), "-o", str(out)])

    assert result.exit_code == 0
    assert out.stat().st_size == 2 * 65536


def test_convert_round_trips_back_to_fds(image: Path, tmp_path: Path) -> None:
    as_qd = tmp_path / "disk.qd"
    back = tmp_path / "back.fds"

    runner.invoke(app, ["convert", str(image), "-o", str(as_qd)])
    runner.invoke(app, ["convert", str(as_qd), "-o", str(back)])

    assert back.read_bytes() == image.read_bytes()


def test_convert_refuses_to_overwrite_without_force(image: Path, tmp_path: Path) -> None:
    out = tmp_path / "taken.qd"
    out.write_bytes(b"existing")

    result = runner.invoke(app, ["convert", str(image), "-o", str(out)])

    assert result.exit_code == 1
    assert out.read_bytes() == b"existing"


def test_convert_overwrites_when_forced(image: Path, tmp_path: Path) -> None:
    out = tmp_path / "taken.qd"
    out.write_bytes(b"existing")

    result = runner.invoke(app, ["convert", str(image), "-o", str(out), "--force"])

    assert result.exit_code == 0
    assert out.read_bytes() != b"existing"


def test_canon_writes_the_canonical_image(image: Path, tmp_path: Path) -> None:
    out = tmp_path / "canon.fds"

    result = runner.invoke(app, ["canon", str(image), "-o", str(out)])

    assert result.exit_code == 0
    assert out.stat().st_size == 2 * SIDE_SIZE
    assert "fdscanon:v1:content/v1:" in result.stdout


def test_canon_accepts_a_profile(image: Path) -> None:
    result = runner.invoke(app, ["canon", str(image), "--profile", "data"])

    assert result.exit_code == 0
    assert "data/v1" in result.stdout


def test_canon_rejects_an_unknown_profile(image: Path) -> None:
    result = runner.invoke(app, ["canon", str(image), "--profile", "nope"])

    assert result.exit_code == 1
    assert "unknown profile" in result.stdout


def test_blank_writes_the_reference_image(tmp_path: Path) -> None:
    out = tmp_path / "blank64.fds"

    result = runner.invoke(app, ["blank", "-o", str(out), "--sides", "1", "--header"])

    assert result.exit_code == 0
    assert out.stat().st_size == 16 + SIDE_SIZE


def test_blank_can_write_a_formatted_disk(tmp_path: Path) -> None:
    out = tmp_path / "formatted.fds"

    runner.invoke(app, ["blank", "-o", str(out), "--sides", "2", "--formatted"])

    assert runner.invoke(app, ["verify", str(out)]).exit_code == 0


def test_a_missing_file_is_reported_without_a_traceback(tmp_path: Path) -> None:
    result = runner.invoke(app, ["info", str(tmp_path / "nope.fds")])

    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_an_unknown_extension_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "disk.bin"
    path.write_bytes(bytes(SIDE_SIZE))

    result = runner.invoke(app, ["info", str(path)])

    assert result.exit_code == 1
    assert "format" in result.stdout


def test_lint_passes_a_plain_image(image: Path) -> None:
    result = runner.invoke(app, ["lint", str(image)])

    assert result.exit_code == 0
    assert "ok" in result.stdout


def test_lint_rejects_an_all_zero_image(tmp_path: Path) -> None:
    path = tmp_path / "blank.fds"
    path.write_bytes(bytes(SIDE_SIZE))

    result = runner.invoke(app, ["lint", str(path)])

    assert result.exit_code == 1
    assert "FK002" in result.stdout


def test_dump_reads_the_simulated_drive(image: Path, tmp_path: Path) -> None:
    out = tmp_path / "dump.fds"

    result = runner.invoke(app, ["dump", "-o", str(out), "--source", str(image)])

    assert result.exit_code == 0
    assert "grade clean" in result.stdout
    assert out.stat().st_size == SIDE_SIZE


def test_dump_needs_a_source_for_the_simulated_backend(tmp_path: Path) -> None:
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.fds")])

    assert result.exit_code == 1
    assert "--source" in result.stdout


def test_dump_can_repeat_a_read_to_check_stability(image: Path, tmp_path: Path) -> None:
    out = tmp_path / "dump.fds"

    result = runner.invoke(
        app,
        ["dump", "-o", str(out), "--source", str(image), "--passes", "3"],
    )

    assert result.exit_code == 0


def test_write_verifies_by_reading_back(single_side: Path, tmp_path: Path) -> None:
    backup = tmp_path / "before.fds"

    result = runner.invoke(
        app,
        [
            "write",
            str(single_side),
            "--source",
            str(single_side),
            "--backup",
            str(backup),
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert "verified True" in result.stdout
    assert backup.exists()


def test_write_stops_when_the_confirmation_is_declined(single_side: Path) -> None:
    result = runner.invoke(
        app,
        ["write", str(single_side), "--source", str(single_side)],
        input="n\n",
    )

    assert result.exit_code == 1
    assert "declined" in result.stdout


def test_write_refuses_a_multi_side_image_in_one_pass(image: Path) -> None:
    result = runner.invoke(app, ["write", str(image), "--source", str(image), "--yes"])

    assert result.exit_code == 1
    assert "one side at a time" in result.stdout


def _dat_for(path: Path, image: Path) -> Path:
    data = image.read_bytes()
    path.write_text(
        "<?xml version='1.0'?>\n<datafile>\n"
        "<header><name>Test DAT</name><version>1</version></header>\n"
        '<game name="Known (Japan)"><rom name="Known (Japan).fds" '
        f'size="{len(data)}" sha1="{hashlib.sha1(data, usedforsecurity=False).hexdigest()}"/>'
        "</game>\n</datafile>\n",
        encoding="utf-8",
    )
    return path


def test_identify_matches_a_known_image(image: Path, tmp_path: Path) -> None:
    dat = _dat_for(tmp_path / "test.dat", image)

    result = runner.invoke(app, ["identify", str(image), "--dat", str(dat)])

    assert result.exit_code == 0
    assert "Known (Japan)" in result.stdout


def test_identify_reports_an_unknown_image(single_side: Path, image: Path, tmp_path: Path) -> None:
    dat = _dat_for(tmp_path / "test.dat", image)

    result = runner.invoke(app, ["identify", str(single_side), "--dat", str(dat)])

    assert result.exit_code == 1
    assert "no match" in result.stdout


def test_identify_reports_a_missing_dat(image: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["identify", str(image), "--dat", str(tmp_path / "nope.dat")])

    assert result.exit_code == 1
    assert "not found" in result.stdout
