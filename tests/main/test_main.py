from __future__ import annotations

import hashlib
import json
import zlib
from collections.abc import Callable
from pathlib import Path

import pytest
from device import FakeFdsStick
from drive_double import FaultPlan, SimulatedDrive
from typer.testing import CliRunner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli import common, hardware_cmds, inspect_cmds
from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds
from fdstoolkit.codecs.fds import SIDE_SIZE
from fdstoolkit.codecs.qd import encode as encode_qd
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.doctor import Check, CheckStatus, DoctorReport
from fdstoolkit.hardware import session
from fdstoolkit.hardware.fdsstick import FdsStick, HidApiTransport
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError
from fdstoolkit.hardware.session import Grade
from fdstoolkit.identify import firmware
from fdstoolkit.quality.surface import Finish, PatternPass, SurfaceReport

runner = CliRunner()
PUBLISHED_HOST = "0.0.0.0"  # noqa: S104 -- the host this test asserts a warning for


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
    assert payload["canonical"].startswith("fdstoolkit:v1:content/v1:")


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
    assert "fdstoolkit:v1:content/v1:" in result.stdout


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


@pytest.mark.parametrize("command", ["blank", "card", "dump", "surface"])
@pytest.mark.parametrize("sides", ["0", "3", "-1", "1.5", "2.0", "two"])
def test_a_side_count_other_than_one_or_two_is_refused(
    command: str, sides: str, tmp_path: Path
) -> None:
    output = ["-o", str(tmp_path / "x.fds")] if command != "surface" else []

    result = runner.invoke(app, [command, *output, "--sides", sides])

    assert result.exit_code == 2
    assert "--sides" in result.output


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


def attach(
    monkeypatch: pytest.MonkeyPatch,
    source: Path | None = None,
    plan: FaultPlan | None = None,
) -> SimulatedDrive:
    """Stand a drive in for the FDSStick the hardware commands open."""
    disk = None
    if source is not None:
        disk, _, _, _ = common.decode_image(source)
    drive = SimulatedDrive(disk, plan=plan) if plan else SimulatedDrive(disk)

    def opener() -> SimulatedDrive:
        return drive

    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", opener)
    return drive


def detach(monkeypatch: pytest.MonkeyPatch, message: str = "no FDSStick is attached") -> None:
    def opener() -> SimulatedDrive:
        raise HardwareFaultError(message, kind=FaultKind.LINK)

    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", opener)


def test_dump_reads_the_disk_in_the_drive(
    image: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attach(monkeypatch, image)
    out = tmp_path / "dump.fds"

    result = runner.invoke(app, ["dump", "-o", str(out)])

    assert result.exit_code == 0
    assert "grade clean" in result.stdout
    assert out.stat().st_size == SIDE_SIZE


def test_dump_refuses_when_no_stick_is_attached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    detach(monkeypatch)

    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.fds")])

    assert result.exit_code == 1
    assert "FDSStick" in result.stdout


def test_dump_can_repeat_a_read_to_check_stability(
    image: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attach(monkeypatch, image)
    out = tmp_path / "dump.fds"

    result = runner.invoke(app, ["dump", "-o", str(out), "--passes", "3"])

    assert result.exit_code == 0


def test_write_verifies_by_reading_back(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attach(monkeypatch, single_side)
    backup = tmp_path / "before.fds"

    result = runner.invoke(
        app,
        ["write", str(single_side), "--backup", str(backup), "--yes"],
    )

    assert result.exit_code == 0
    assert "verified True" in result.stdout
    assert backup.exists()


def test_write_stops_when_the_confirmation_is_declined(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attach(monkeypatch, single_side)

    result = runner.invoke(app, ["write", str(single_side)], input="n\n")

    assert result.exit_code == 1
    assert "declined" in result.stdout


def test_write_refuses_a_multi_side_image_in_one_pass(
    image: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attach(monkeypatch, image)

    result = runner.invoke(app, ["write", str(image), "--yes"])

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


def test_extract_writes_every_file(tmp_path: Path) -> None:
    content = bytearray(blank_image(sides=1, headered=False, formatted=True))
    content[56:58] = bytes([0x02, 0x01])
    header = (
        bytes([0x03, 0x00, 0x00])
        + b"HELLO   "
        + (0x6000).to_bytes(2, "little")
        + (4).to_bytes(2, "little")
        + bytes([0x00])
    )
    content[58:74] = header
    content[74:79] = bytes([0x04]) + bytes([0xAB]) * 4
    source = tmp_path / "with-file.fds"
    source.write_bytes(bytes(content))
    out = tmp_path / "files"

    result = runner.invoke(app, ["extract", str(source), "-d", str(out)])

    assert result.exit_code == 0
    assert (out / "side0-00-HELLO.bin").read_bytes() == bytes([0xAB]) * 4


def test_insert_adds_a_file(single_side: Path, tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(bytes([0x42]) * 32)
    out = tmp_path / "with-new.fds"

    result = runner.invoke(
        app,
        [
            "insert",
            str(single_side),
            "-o",
            str(out),
            "--file",
            str(payload),
            "--name",
            "NEW",
        ],
    )

    assert result.exit_code == 0
    listing = runner.invoke(app, ["ls", str(out)])
    assert "NEW" in listing.stdout


def test_insert_reports_a_name_that_is_too_long(single_side: Path, tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"\x01")

    result = runner.invoke(
        app,
        [
            "insert",
            str(single_side),
            "-o",
            str(tmp_path / "out.fds"),
            "--file",
            str(payload),
            "--name",
            "WAYTOOLONG",
        ],
    )

    assert result.exit_code == 1
    assert "eight characters" in result.stdout


def test_patch_applies_an_ips(single_side: Path, tmp_path: Path) -> None:
    patch = tmp_path / "rename.ips"
    patch.write_bytes(
        b"PATCH" + (0x10).to_bytes(3, "big") + (3).to_bytes(2, "big") + b"ZEL" + b"EOF"
    )
    out = tmp_path / "patched.fds"

    result = runner.invoke(
        app,
        ["patch", str(single_side), "--patch", str(patch), "-o", str(out)],
    )

    assert result.exit_code == 0
    assert "applied ips" in result.stdout
    assert (
        json.loads(runner.invoke(app, ["info", str(out), "--json"]).stdout)["sides"][0]["game_name"]
        == "ZEL"
    )


def test_patch_reports_a_missing_patch_file(single_side: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "patch",
            str(single_side),
            "--patch",
            str(tmp_path / "nope.ips"),
            "-o",
            str(tmp_path / "o.fds"),
        ],
    )

    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_patch_reports_an_unknown_format(single_side: Path, tmp_path: Path) -> None:
    patch = tmp_path / "bad.ips"
    patch.write_bytes(b"nonsense")

    result = runner.invoke(
        app,
        ["patch", str(single_side), "--patch", str(patch), "-o", str(tmp_path / "o.fds")],
    )

    assert result.exit_code == 1
    assert "unknown patch format" in result.stdout


def test_provenance_reports_each_side(image: Path) -> None:
    result = runner.invoke(app, ["provenance", str(image)])

    assert result.exit_code == 0
    assert "factory" in result.stdout


def test_provenance_as_json_lists_every_side(image: Path) -> None:
    payload = json.loads(runner.invoke(app, ["provenance", str(image), "--json"]).stdout)

    assert len(payload["sides"]) == 2
    assert payload["sides"][0]["origin"] == "factory"


def test_saves_reports_no_candidate_for_identical_dumps(single_side: Path) -> None:
    result = runner.invoke(app, ["saves", str(single_side), str(single_side)])

    assert result.exit_code == 0
    assert "no save candidate" in result.stdout


def test_saves_needs_two_dumps(single_side: Path) -> None:
    result = runner.invoke(app, ["saves", str(single_side)])

    assert result.exit_code == 1
    assert "at least two" in result.stdout


def test_dump_reports_a_missing_fdsstick(tmp_path: Path) -> None:
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.fds")])

    assert result.exit_code == 1
    assert "FDSStick" in result.stdout or "hidapi" in result.stdout


def test_write_reports_a_missing_fdsstick(single_side: Path) -> None:
    result = runner.invoke(app, ["write", str(single_side), "--yes"])

    assert result.exit_code == 1
    assert "FDSStick" in result.stdout or "hidapi" in result.stdout


def test_clean_removes_trailing_data(tmp_path: Path) -> None:
    raw = bytearray(blank_image(sides=1, headered=False, formatted=True))
    raw[70:74] = bytes([0xDE, 0xAD, 0xBE, 0xEF])
    source = tmp_path / "stale.fds"
    source.write_bytes(bytes(raw))
    out = tmp_path / "clean.fds"

    result = runner.invoke(app, ["clean", str(source), "-o", str(out)])

    assert result.exit_code == 0
    assert "removed 16 trailing byte" in result.stdout
    assert out.read_bytes() == blank_image(sides=1, headered=False, formatted=True)


def test_diff_reports_identical_images(single_side: Path) -> None:
    result = runner.invoke(app, ["diff", str(single_side), str(single_side)])

    assert result.exit_code == 0
    assert "identical" in result.stdout


def test_diff_reports_a_difference(single_side: Path, image: Path) -> None:
    result = runner.invoke(app, ["diff", str(single_side), str(image)])

    assert result.exit_code == 1
    assert "side count" in result.stdout


def test_consensus_merges_identical_dumps(single_side: Path, tmp_path: Path) -> None:
    out = tmp_path / "merged.fds"

    result = runner.invoke(
        app,
        ["consensus", str(single_side), str(single_side), "-o", str(out)],
    )

    assert result.exit_code == 0
    assert out.read_bytes() == single_side.read_bytes()


def test_consensus_needs_two_dumps(single_side: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["consensus", str(single_side), "-o", str(tmp_path / "m.fds")])

    assert result.exit_code == 1
    assert "at least two" in result.stdout


def test_save_extract_then_apply_round_trips(single_side: Path, tmp_path: Path) -> None:
    played = tmp_path / "played.fds"
    data = bytearray(single_side.read_bytes())
    data[70:78] = bytes([0x22]) * 8
    played.write_bytes(bytes(data))
    save = tmp_path / "save.ips"
    merged = tmp_path / "merged.fds"

    extracted = runner.invoke(
        app,
        ["save-extract", str(single_side), "--played", str(played), "-o", str(save)],
    )
    applied = runner.invoke(
        app,
        ["save-apply", str(single_side), "--save", str(save), "-o", str(merged)],
    )

    assert extracted.exit_code == 0
    assert applied.exit_code == 0
    assert merged.read_bytes() == played.read_bytes()


def test_save_apply_reports_a_missing_save(single_side: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "save-apply",
            str(single_side),
            "--save",
            str(tmp_path / "nope.ips"),
            "-o",
            str(tmp_path / "out.fds"),
        ],
    )

    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_save_extract_reports_a_missing_played_image(single_side: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "save-extract",
            str(single_side),
            "--played",
            str(tmp_path / "nope.fds"),
            "-o",
            str(tmp_path / "out.ips"),
        ],
    )

    assert result.exit_code == 1
    assert "not found" in result.stdout


@pytest.fixture
def hidden_file_image(tmp_path: Path) -> Path:
    content = bytearray(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    content[56:58] = bytes([0x02, 0x00])
    header = (
        bytes([0x03, 0x00, 0x00])
        + b"SECRET  "
        + (0x6000).to_bytes(2, "little")
        + (4).to_bytes(2, "little")
        + bytes([0x00])
    )
    content[58:74] = header
    content[74:79] = bytes([0x04]) + bytes([0x55]) * 4
    path = tmp_path / "hidden.fds"
    path.write_bytes(bytes(content))
    return path


def test_info_prints_its_findings(damaged: Path) -> None:
    result = runner.invoke(app, ["info", str(damaged)])

    assert "FDS008" in result.stdout


def test_ls_can_emit_json(hidden_file_image: Path) -> None:
    payload = json.loads(runner.invoke(app, ["ls", str(hidden_file_image), "--json"]).stdout)

    assert payload["files"][0]["name"] == "SECRET"
    assert payload["files"][0]["hidden"] is True


def test_ls_marks_a_hidden_file(hidden_file_image: Path) -> None:
    result = runner.invoke(app, ["ls", str(hidden_file_image)])

    assert "(hidden)" in result.stdout


def test_verify_can_emit_json(image: Path) -> None:
    payload = json.loads(runner.invoke(app, ["verify", str(image), "--json"]).stdout)

    assert payload["ok"] is True
    assert payload["worst_severity"] == "info"


def test_hash_prints_a_human_report(image: Path) -> None:
    result = runner.invoke(app, ["hash", str(image)])

    assert "sha256" in result.stdout
    assert "canonical fdstoolkit:v1:content/v1:" in result.stdout


def test_hash_rejects_an_unknown_profile(image: Path) -> None:
    result = runner.invoke(app, ["hash", str(image), "--profile", "nope"])

    assert result.exit_code == 1
    assert "unknown profile" in result.stdout


def test_convert_reports_a_side_that_will_not_fit_the_target(tmp_path: Path) -> None:
    info = bytearray(56)
    info[0] = 0x01
    info[1:15] = b"*NINTENDO-HVC*"
    size = 65450
    header = (
        bytes([0x03, 0x00, 0x00])
        + b"BIG     "
        + (0x6000).to_bytes(2, "little")
        + size.to_bytes(2, "little")
        + bytes([0x00])
    )
    side = Side(
        blocks=(
            Block(kind=BlockKind.DISK_INFO, payload=bytes(info)),
            Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([0x02, 0x01])),
            Block(kind=BlockKind.FILE_HEADER, payload=header),
            Block(kind=BlockKind.FILE_DATA, payload=bytes([0x04]) + bytes(size)),
        ),
        tail=b"",
        capacity=65536,
    )
    data, _ = encode_qd(Disk(sides=(side,)))
    source = tmp_path / "big.qd"
    source.write_bytes(data)
    out = tmp_path / "big.fds"

    result = runner.invoke(app, ["convert", str(source), "-o", str(out)])

    assert result.exit_code == 1
    assert "FDS011" in result.stdout


def test_extract_refuses_to_overwrite(hidden_file_image: Path, tmp_path: Path) -> None:
    target = tmp_path / "files"
    target.mkdir()
    (target / "side0-00-SECRET.bin").write_bytes(b"old")

    result = runner.invoke(app, ["extract", str(hidden_file_image), "-d", str(target)])

    assert result.exit_code == 1
    assert "--force" in result.stdout


def test_insert_reports_a_missing_file(single_side: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "insert",
            str(single_side),
            "-o",
            str(tmp_path / "out.fds"),
            "--file",
            str(tmp_path / "nope.bin"),
            "--name",
            "NEW",
        ],
    )

    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_insert_can_write_a_qd(single_side: Path, tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(bytes([0x42]) * 8)
    out = tmp_path / "with-new.qd"

    result = runner.invoke(
        app,
        [
            "insert",
            str(single_side),
            "-o",
            str(out),
            "--file",
            str(payload),
            "--name",
            "NEW",
        ],
    )

    assert result.exit_code == 0
    assert out.stat().st_size == 65536


def test_provenance_prints_its_notes(tmp_path: Path) -> None:
    raw = bytearray(blank_image(sides=1, headered=False, formatted=True))
    raw[0x34] = 0xAF
    path = tmp_path / "odd.fds"
    path.write_bytes(bytes(raw))

    result = runner.invoke(app, ["provenance", str(path)])

    assert "rewrite count" in result.stdout


def test_saves_can_emit_json(single_side: Path) -> None:
    payload = json.loads(
        runner.invoke(app, ["saves", str(single_side), str(single_side), "--json"]).stdout
    )

    assert payload["candidates"] == []


def test_saves_reports_a_candidate(tmp_path: Path) -> None:
    def with_save(fill: int) -> Path:
        content = bytearray(blank_image(sides=1, headered=False, formatted=True))
        content[56:58] = bytes([0x02, 0x01])
        header = (
            bytes([0x03, 0x00, 0x00])
            + b"FC_SAVE "
            + (0x6000).to_bytes(2, "little")
            + (4).to_bytes(2, "little")
            + bytes([0x00])
        )
        content[58:74] = header
        content[74:79] = bytes([0x04]) + bytes([fill]) * 4
        path = tmp_path / f"save{fill}.fds"
        path.write_bytes(bytes(content))
        return path

    result = runner.invoke(app, ["saves", str(with_save(1)), str(with_save(2))])

    assert "FC_SAVE" in result.stdout
    assert "name reads like a save" in result.stdout


def test_dump_reports_unstable_blocks(
    image: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attach(monkeypatch, image)

    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "d.fds"), "--passes", "2"])

    assert result.exit_code == 0


def test_dump_reports_a_drive_fault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "empty.fds"
    empty.write_bytes(bytes(SIDE_SIZE))
    attach(monkeypatch, empty)

    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "d.fds"), "--sides", "2"])

    assert result.exit_code == 1


def test_clean_can_write_a_qd(single_side: Path, tmp_path: Path) -> None:
    out = tmp_path / "clean.qd"

    result = runner.invoke(app, ["clean", str(single_side), "-o", str(out)])

    assert result.exit_code == 0
    assert out.stat().st_size == 65536


def test_diff_can_emit_json(single_side: Path) -> None:
    payload = json.loads(
        runner.invoke(app, ["diff", str(single_side), str(single_side), "--json"]).stdout
    )

    assert payload["identical"] is True


def test_diff_lists_the_blocks_that_differ(single_side: Path, tmp_path: Path) -> None:
    other = tmp_path / "other.fds"
    data = bytearray(single_side.read_bytes())
    data[57] = 0x01
    other.write_bytes(bytes(data))

    result = runner.invoke(app, ["diff", str(single_side), str(other)])

    assert result.exit_code == 1
    assert "side 0 block" in result.stdout


def test_consensus_reports_a_disagreement(single_side: Path, tmp_path: Path) -> None:
    other = tmp_path / "other.fds"
    data = bytearray(single_side.read_bytes())
    data[57] = 0x01
    other.write_bytes(bytes(data))

    result = runner.invoke(
        app,
        ["consensus", str(single_side), str(other), "-o", str(tmp_path / "merged.fds")],
    )

    assert result.exit_code == 1
    assert "disagree" in result.stdout


def test_identify_can_emit_json(image: Path, tmp_path: Path) -> None:
    dat = _dat_for(tmp_path / "test.dat", image)

    payload = json.loads(
        runner.invoke(app, ["identify", str(image), "--dat", str(dat), "--json"]).stdout
    )

    assert payload["kind"] == "exact"


def test_identify_lists_entries_of_the_same_size(image: Path, tmp_path: Path) -> None:
    dat = _dat_for(tmp_path / "test.dat", image)
    other = tmp_path / "other.fds"
    data = bytearray(image.read_bytes())
    data[0x10:0x13] = b"XYZ"
    other.write_bytes(bytes(data))

    result = runner.invoke(app, ["identify", str(other), "--dat", str(dat)])

    assert "same size" in result.stdout


def test_save_apply_reports_an_unusable_save(single_side: Path, tmp_path: Path) -> None:
    save = tmp_path / "save.bin"
    save.write_bytes(bytes([0x01, 0x02, 0x03]))

    result = runner.invoke(
        app,
        [
            "save-apply",
            str(single_side),
            "--save",
            str(save),
            "-o",
            str(tmp_path / "out.fds"),
        ],
    )

    assert result.exit_code == 1
    assert "not a save" in result.stdout


def test_save_extract_refuses_an_unknown_format(single_side: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "save-extract",
            str(single_side),
            "--played",
            str(single_side),
            "-o",
            str(tmp_path / "out.bin"),
            "--format",
            "unknown",
        ],
    )

    assert result.exit_code == 1
    assert "cannot write" in result.stdout


def test_blank_reports_an_invalid_game_name(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["blank", "-o", str(tmp_path / "b.fds"), "--game-name", "TOOLONG"],
    )

    assert result.exit_code == 1
    assert "three characters" in result.stdout


def test_saves_as_json_lists_a_candidate(tmp_path: Path) -> None:
    def with_save(fill: int) -> Path:
        content = bytearray(blank_image(sides=1, headered=False, formatted=True))
        content[56:58] = bytes([0x02, 0x01])
        header = (
            bytes([0x03, 0x00, 0x00])
            + b"FC_SAVE "
            + (0x6000).to_bytes(2, "little")
            + (4).to_bytes(2, "little")
            + bytes([0x00])
        )
        content[58:74] = header
        content[74:79] = bytes([0x04]) + bytes([fill]) * 4
        path = tmp_path / f"json-save{fill}.fds"
        path.write_bytes(bytes(content))
        return path

    payload = json.loads(
        runner.invoke(app, ["saves", str(with_save(3)), str(with_save(4)), "--json"]).stdout
    )

    assert payload["candidates"][0]["name"] == "FC_SAVE"


def test_dump_names_a_block_that_differs_between_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.fds"
    source.write_bytes(blank_image(sides=1, headered=False, formatted=True))

    attach(monkeypatch, source, plan=FaultPlan(unstable_blocks=frozenset({1})))

    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "d.fds"), "--passes", "2"])

    assert "differs between passes" in result.stdout


def test_write_names_a_block_that_did_not_stick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.fds"
    source.write_bytes(blank_image(sides=1, headered=False, formatted=True))

    attach(monkeypatch, source, plan=FaultPlan(unstable_blocks=frozenset({1})))

    result = runner.invoke(app, ["write", str(source), "--yes"])

    assert "did not read back as written" in result.stdout


def test_identify_reports_a_file_that_is_not_a_dat(image: Path, tmp_path: Path) -> None:
    dat = tmp_path / "wrong.xml"
    dat.write_text("<other/>", encoding="utf-8")

    result = runner.invoke(app, ["identify", str(image), "--dat", str(dat)])

    assert result.exit_code == 1
    assert "not a DAT" in result.stdout


def test_insert_reports_a_finding_from_the_encoder(tmp_path: Path) -> None:
    info = bytearray(56)
    info[0] = 0x01
    info[1:15] = b"*NINTENDO-HVC*"
    size = 65028
    header = (
        bytes([0x03, 0x00, 0x00])
        + b"BIG     "
        + (0x6000).to_bytes(2, "little")
        + size.to_bytes(2, "little")
        + bytes([0x00])
    )
    side = Side(
        blocks=(
            Block(kind=BlockKind.DISK_INFO, payload=bytes(info)),
            Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([0x02, 0x01])),
            Block(kind=BlockKind.FILE_HEADER, payload=header),
            Block(kind=BlockKind.FILE_DATA, payload=bytes([0x04]) + bytes(size)),
        ),
        tail=b"",
        capacity=65536,
    )
    data, _ = encode_qd(Disk(sides=(side,)))
    source = tmp_path / "nearly-full.qd"
    source.write_bytes(data)
    payload = tmp_path / "payload.bin"
    payload.write_bytes(bytes(400))

    result = runner.invoke(
        app,
        [
            "insert",
            str(source),
            "-o",
            str(tmp_path / "out.fds"),
            "--file",
            str(payload),
            "--name",
            "NEW",
        ],
    )

    assert "FDS011" in result.stdout


def test_lint_can_emit_json(image: Path) -> None:
    payload = json.loads(runner.invoke(app, ["lint", str(image), "--json"]).stdout)

    assert payload["ok"] is True
    assert payload["findings"] == []


def test_card_writes_a_blank_the_firmware_accepts(tmp_path: Path) -> None:
    out = tmp_path / "blank.fds"

    result = runner.invoke(app, ["card", "-o", str(out), "--sides", "2"])

    assert result.exit_code == 0
    assert runner.invoke(app, ["lint", str(out)]).exit_code == 0


def test_card_can_write_the_released_firmware_variant(tmp_path: Path) -> None:
    out = tmp_path / "zeros.fds"

    result = runner.invoke(app, ["card", "-o", str(out), "--firmware", "released"])

    assert result.exit_code == 0
    assert out.read_bytes() == bytes(SIDE_SIZE)


def test_card_refuses_to_overwrite(tmp_path: Path) -> None:
    out = tmp_path / "blank.fds"
    out.write_bytes(b"old")

    result = runner.invoke(app, ["card", "-o", str(out)])

    assert result.exit_code == 1
    assert "--force" in result.stdout


def test_split_then_join_round_trips(image: Path, tmp_path: Path) -> None:
    sides = tmp_path / "sides"
    rebuilt = tmp_path / "rebuilt.fds"

    split_result = runner.invoke(app, ["split", str(image), "-d", str(sides), "--stem", "game"])
    files = sorted(str(path) for path in sides.iterdir())
    join_result = runner.invoke(app, ["join", *files, "-o", str(rebuilt)])

    assert split_result.exit_code == 0
    assert join_result.exit_code == 0
    assert rebuilt.read_bytes() == image.read_bytes()


def test_split_refuses_to_overwrite(image: Path, tmp_path: Path) -> None:
    sides = tmp_path / "sides"
    sides.mkdir()
    (sides / "game.A").write_bytes(b"old")

    result = runner.invoke(app, ["split", str(image), "-d", str(sides), "--stem", "game"])

    assert result.exit_code == 1
    assert "--force" in result.stdout


def test_join_reports_a_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["join", str(tmp_path / "nope.A"), "-o", str(tmp_path / "out.fds")],
    )

    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_join_reports_a_file_without_a_side_letter(tmp_path: Path) -> None:
    odd = tmp_path / "game.zzz"
    odd.write_bytes(bytes(SIDE_SIZE))

    result = runner.invoke(app, ["join", str(odd), "-o", str(tmp_path / "out.fds")])

    assert result.exit_code == 1
    assert "side letter" in result.stdout


def test_build_writes_a_disk_from_a_manifest(tmp_path: Path) -> None:
    payload = tmp_path / "main.prg"
    payload.write_bytes(bytes([0x11]) * 32)
    manifest = tmp_path / "disk.json"
    manifest.write_text(
        json.dumps(
            {
                "game_name": "SMB",
                "sides": [
                    {
                        "side": 0,
                        "files": [{"name": "MAIN", "address": "0x6000", "path": "main.prg"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "built.fds"

    result = runner.invoke(app, ["build", str(manifest), "-o", str(out)])

    assert result.exit_code == 0
    assert runner.invoke(app, ["verify", str(out), "--strict"]).exit_code == 0
    assert "MAIN" in runner.invoke(app, ["ls", str(out)]).stdout


def test_build_reports_a_missing_manifest(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["build", str(tmp_path / "nope.json"), "-o", str(tmp_path / "out.fds")],
    )

    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_build_reports_a_manifest_that_does_not_parse(tmp_path: Path) -> None:
    manifest = tmp_path / "bad.json"
    manifest.write_text(json.dumps({"game_name": "SMB", "sides": []}), encoding="utf-8")

    result = runner.invoke(app, ["build", str(manifest), "-o", str(tmp_path / "out.fds")])

    assert result.exit_code == 1
    assert "at least one side" in result.stdout


def test_set_changes_a_field(single_side: Path, tmp_path: Path) -> None:
    out = tmp_path / "renamed.fds"

    result = runner.invoke(
        app,
        ["set", str(single_side), "-o", str(out), "--set", "game_name=ZEL"],
    )

    assert result.exit_code == 0
    assert "game_name: SMB -> ZEL" in result.stdout
    payload = json.loads(runner.invoke(app, ["info", str(out), "--json"]).stdout)
    assert payload["sides"][0]["game_name"] == "ZEL"


def test_set_can_write_a_qd(single_side: Path, tmp_path: Path) -> None:
    out = tmp_path / "renamed.qd"

    result = runner.invoke(
        app,
        ["set", str(single_side), "-o", str(out), "--set", "game_version=2"],
    )

    assert result.exit_code == 0
    assert out.stat().st_size == 65536


def test_set_reports_an_unknown_field(single_side: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["set", str(single_side), "-o", str(tmp_path / "o.fds"), "--set", "colour=blue"],
    )

    assert result.exit_code == 1
    assert "unknown field" in result.stdout


def test_surface_grades_a_healthy_disk(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attach(monkeypatch, single_side)

    result = runner.invoke(
        app,
        ["surface", "--yes", "--backup", str(tmp_path / "b.fds")],
    )

    assert result.exit_code == 0
    assert "grade clean" in result.stdout


def test_surface_stops_when_declined(single_side: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attach(monkeypatch, single_side)

    result = runner.invoke(app, ["surface"], input="n\n")

    assert result.exit_code == 1
    assert "declined" in result.stdout


def test_surface_runs_without_a_backup(single_side: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attach(monkeypatch, single_side)

    result = runner.invoke(app, ["surface", "--yes"])

    assert result.exit_code == 0


def _save_disk(tmp_path: Path, fill: int, name: str) -> Path:
    content = bytearray(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    content[56:58] = bytes([0x02, 0x01])
    header = (
        bytes([0x03, 0x00, 0x00])
        + b"FC_SAVE "
        + (0x6000).to_bytes(2, "little")
        + (4).to_bytes(2, "little")
        + bytes([0x00])
    )
    content[58:74] = header
    content[74:79] = bytes([0x04]) + bytes([fill]) * 4
    path = tmp_path / name
    path.write_bytes(bytes(content))
    return path


def _recipes(tmp_path: Path) -> Path:
    path = tmp_path / "recipes.json"
    path.write_text(
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
                        "source": "two dumps of one release differ only here",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_normalise_saves_makes_two_played_copies_agree(tmp_path: Path) -> None:
    one = _save_disk(tmp_path, 0x11, "one.fds")
    two = _save_disk(tmp_path, 0x22, "two.fds")
    recipes = _recipes(tmp_path)

    first = runner.invoke(
        app,
        ["normalise-saves", str(one), "-o", str(tmp_path / "a.fds"), "--recipes", str(recipes)],
    )
    second = runner.invoke(
        app,
        ["normalise-saves", str(two), "-o", str(tmp_path / "b.fds"), "--recipes", str(recipes)],
    )

    assert first.exit_code == 0
    assert "FC_SAVE" in first.stdout
    assert second.exit_code == 0
    assert (tmp_path / "a.fds").read_bytes() == (tmp_path / "b.fds").read_bytes()


def test_normalise_saves_says_when_nothing_matched(single_side: Path, tmp_path: Path) -> None:
    recipes = tmp_path / "other.json"
    recipes.write_text(
        json.dumps(
            {
                "version": 1,
                "recipes": [
                    {
                        "game_name": "ZEL",
                        "game_version": 0,
                        "side": 0,
                        "position": 0,
                        "fill": 0,
                        "source": "x",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "normalise-saves",
            str(single_side),
            "-o",
            str(tmp_path / "out.fds"),
            "--recipes",
            str(recipes),
        ],
    )

    assert result.exit_code == 0
    assert "no recipe matched" in result.stdout


def test_normalise_saves_reports_a_missing_recipe_file(single_side: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "normalise-saves",
            str(single_side),
            "-o",
            str(tmp_path / "out.fds"),
            "--recipes",
            str(tmp_path / "nope.json"),
        ],
    )

    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_normalise_saves_reports_a_recipe_file_that_does_not_parse(
    single_side: Path,
    tmp_path: Path,
) -> None:
    recipes = tmp_path / "bad.json"
    recipes.write_text(json.dumps({"version": 99, "recipes": []}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "normalise-saves",
            str(single_side),
            "-o",
            str(tmp_path / "out.fds"),
            "--recipes",
            str(recipes),
        ],
    )

    assert result.exit_code == 1
    assert "version" in result.stdout


def test_normalise_saves_can_write_a_qd(tmp_path: Path) -> None:
    source = _save_disk(tmp_path, 0x33, "played.fds")
    out = tmp_path / "clean.qd"

    result = runner.invoke(
        app,
        ["normalise-saves", str(source), "-o", str(out), "--recipes", str(_recipes(tmp_path))],
    )

    assert result.exit_code == 0
    assert out.stat().st_size == 65536


def test_the_version_flag_prints_the_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.startswith("fdstoolkit ")


def test_the_help_lists_the_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "verify" in result.stdout


def test_dump_stops_cleanly_on_an_interrupt(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attach(monkeypatch, single_side)
    original = session.dump

    def interrupt(*_: object, **__: object) -> object:
        raise KeyboardInterrupt

    hardware_cmds.dump_disk = interrupt  # type: ignore[assignment]
    try:
        result = runner.invoke(app, ["dump", "-o", str(tmp_path / "d.fds")])
    finally:
        hardware_cmds.dump_disk = original  # type: ignore[assignment]

    assert result.exit_code == 1
    assert "nothing was written" in result.stdout


def test_write_warns_when_an_interrupt_lands_mid_write(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attach(monkeypatch, single_side)
    original = session.write_verified

    def interrupt(*_: object, **__: object) -> object:
        raise KeyboardInterrupt

    hardware_cmds.write_verified = interrupt  # type: ignore[assignment]
    try:
        result = runner.invoke(app, ["write", str(single_side), "--yes"])
    finally:
        hardware_cmds.write_verified = original  # type: ignore[assignment]

    assert result.exit_code == 1
    assert "half written" in result.stdout


def test_identify_reads_the_cache_on_a_second_run(image: Path, tmp_path: Path) -> None:
    dat = _dat_for(tmp_path / "test.dat", image)
    runner.invoke(app, ["identify", str(image), "--dat", str(dat), "--json"])

    payload = json.loads(
        runner.invoke(app, ["identify", str(image), "--dat", str(dat), "--json"]).stdout
    )

    assert payload["cached"]


def test_identify_can_skip_the_cache(image: Path, tmp_path: Path) -> None:
    dat = _dat_for(tmp_path / "test.dat", image)

    payload = json.loads(
        runner.invoke(
            app, ["identify", str(image), "--dat", str(dat), "--no-cache", "--json"]
        ).stdout
    )

    assert not payload["cached"]


def test_identify_without_the_cache_still_reports_a_missing_dat(
    image: Path, tmp_path: Path
) -> None:
    result = runner.invoke(
        app, ["identify", str(image), "--dat", str(tmp_path / "nope.dat"), "--no-cache"]
    )

    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_identify_reports_the_nearest_reference_image(
    single_side: Path, image: Path, tmp_path: Path
) -> None:
    dat = _dat_for(tmp_path / "test.dat", image)
    references = tmp_path / "known"
    references.mkdir()
    close = bytearray(single_side.read_bytes())
    close[0x34] = 0x03
    (references / "close.fds").write_bytes(bytes(close))

    result = runner.invoke(
        app,
        ["identify", str(single_side), "--dat", str(dat), "--reference", str(references)],
    )

    assert result.exit_code == 1
    assert "near match: close.fds" in result.stdout
    assert "1 byte(s) differ" in result.stdout


def test_identify_reports_a_far_candidate_as_the_nearest_one(
    single_side: Path, image: Path, tmp_path: Path
) -> None:
    dat = _dat_for(tmp_path / "test.dat", image)
    references = tmp_path / "known"
    references.mkdir()
    far = bytearray(single_side.read_bytes())
    for offset in range(40000):
        far[offset] ^= 0xFF
    (references / "far.fds").write_bytes(bytes(far))

    result = runner.invoke(
        app,
        [
            "identify",
            str(single_side),
            "--dat",
            str(dat),
            "--reference",
            str(references),
            "--json",
        ],
    )

    payload = json.loads(result.stdout)
    assert not payload["nearest"]["near"]
    assert payload["nearest"]["truncated_runs"] is False


def test_identify_prints_every_differing_run(
    single_side: Path, image: Path, tmp_path: Path
) -> None:
    dat = _dat_for(tmp_path / "test.dat", image)
    references = tmp_path / "known"
    references.mkdir()
    close = bytearray(single_side.read_bytes())
    for offset in range(0, 200, 2):
        close[offset] ^= 0xFF
    (references / "close.fds").write_bytes(bytes(close))

    result = runner.invoke(
        app,
        ["identify", str(single_side), "--dat", str(dat), "--reference", str(references)],
    )

    assert "more runs not shown" in result.stdout


def test_dat_cache_reports_what_it_holds(image: Path, tmp_path: Path) -> None:
    dat = _dat_for(tmp_path / "test.dat", image)
    runner.invoke(app, ["identify", str(image), "--dat", str(dat)])

    result = runner.invoke(app, ["dat-cache"])

    assert result.exit_code == 0
    assert "1 cached catalogue(s)" in result.stdout


def test_dat_cache_can_be_cleared(image: Path, tmp_path: Path) -> None:
    dat = _dat_for(tmp_path / "test.dat", image)
    runner.invoke(app, ["identify", str(image), "--dat", str(dat)])

    result = runner.invoke(app, ["dat-cache", "--clear"])

    assert "removed 1 cached catalogue(s)" in result.stdout
    assert "0 cached catalogue(s)" in runner.invoke(app, ["dat-cache"]).stdout


def test_diff_explains_two_identical_images(image: Path) -> None:
    result = runner.invoke(app, ["diff", str(image), str(image), "--explain"])

    assert result.exit_code == 0
    assert result.stdout.startswith("identical")


def test_diff_explains_a_changed_field(image: Path, tmp_path: Path) -> None:
    other = tmp_path / "other.fds"
    runner.invoke(app, ["set", str(image), "-o", str(other), "--set", "game_version=2"])

    result = runner.invoke(app, ["diff", str(image), str(other), "--explain"])

    assert result.exit_code == 1
    assert "different software" in result.stdout
    assert "game_version (identity): 0x00 against 0x02" in result.stdout


def test_diff_can_explain_as_json(image: Path, tmp_path: Path) -> None:
    other = tmp_path / "other.fds"
    runner.invoke(app, ["set", str(image), "-o", str(other), "--set", "rewrite_count=3"])

    payload = json.loads(
        runner.invoke(app, ["diff", str(image), str(other), "--explain", "--json"]).stdout
    )

    assert payload["same_software"]
    assert payload["fields"][0]["field"] == "rewrite_count"


def test_rebuild_reports_that_there_is_nothing_to_repair(image: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["rebuild", str(image), "-o", str(tmp_path / "out.fds")])

    assert result.exit_code == 0
    assert "nothing to repair" in result.stdout


def test_rebuild_drops_trailing_data(tmp_path: Path) -> None:
    raw = bytearray(blank_image(sides=1, headered=False, formatted=True))
    raw[-4:] = b"junk"
    source = tmp_path / "tail.fds"
    source.write_bytes(bytes(raw))
    output = tmp_path / "clean.fds"

    result = runner.invoke(app, ["rebuild", str(source), "-o", str(output)])

    assert "trailing byte(s) removed" in result.stdout
    assert output.read_bytes().endswith(bytes(4))


def test_rebuild_recomputes_checksums_in_a_qd(tmp_path: Path) -> None:
    disk = Disk(
        sides=(
            Side(
                blocks=(
                    Block(
                        kind=BlockKind.DISK_INFO,
                        payload=blank_image(sides=1, headered=False, formatted=True)[:56],
                        stored_crc=0,
                    ),
                ),
                tail=b"",
                capacity=SIDE_SIZE,
            ),
        )
    )
    source = tmp_path / "null.qd"
    source.write_bytes(encode_qd(disk)[0])
    output = tmp_path / "fixed.qd"

    result = runner.invoke(app, ["rebuild", str(source), "-o", str(output)])

    assert "checksum(s) recomputed" in result.stdout


def test_rebuild_refuses_two_conflicting_options(image: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "rebuild",
            str(image),
            "-o",
            str(tmp_path / "out.fds"),
            "--reveal-hidden",
            "--drop-hidden",
        ],
    )

    assert result.exit_code == 1
    assert "either reveal or drop" in result.stdout


def test_consensus_prints_a_stability_map(single_side: Path, tmp_path: Path) -> None:
    other = tmp_path / "second.fds"
    other.write_bytes(single_side.read_bytes())
    output = tmp_path / "merged.fds"

    result = runner.invoke(
        app, ["consensus", str(single_side), str(other), "-o", str(output), "--map"]
    )

    assert result.exit_code == 0
    assert "disk_info" in result.stdout
    assert "100.0%" in result.stdout


def test_diff_explains_a_file_difference(single_side: Path, tmp_path: Path) -> None:
    payload = tmp_path / "main.prg"
    payload.write_bytes(bytes([0xAA]) * 8)
    other = tmp_path / "with-file.fds"
    runner.invoke(
        app,
        [
            "insert",
            str(single_side),
            "-o",
            str(other),
            "--file",
            str(payload),
            "--name",
            "MAIN",
        ],
    )

    result = runner.invoke(app, ["diff", str(single_side), str(other), "--explain"])

    assert result.exit_code == 1
    assert "file 0 MAIN: added, 8 bytes" in result.stdout


def test_layout_reports_the_stream_and_the_files(tmp_path: Path) -> None:
    payload = tmp_path / "main.prg"
    payload.write_bytes(bytes([0xAA]) * 4096)
    source = tmp_path / "one.fds"
    source.write_bytes(blank_image(sides=1, headered=False, formatted=True))
    built = tmp_path / "built.fds"
    runner.invoke(
        app,
        ["insert", str(source), "-o", str(built), "--file", str(payload), "--name", "MAIN"],
    )

    result = runner.invoke(app, ["layout", str(built)])

    assert result.exit_code == 0
    assert "s to read end to end" in result.stdout
    assert "MAIN" in result.stdout


def test_layout_reports_dead_weight(tmp_path: Path) -> None:
    raw = bytearray(blank_image(sides=1, headered=False, formatted=True))
    raw[-4:] = b"junk"
    source = tmp_path / "tail.fds"
    source.write_bytes(bytes(raw))

    result = runner.invoke(app, ["layout", str(source)])

    assert "dead weight" in result.stdout


def test_layout_can_emit_json(tmp_path: Path) -> None:
    payload = tmp_path / "a.prg"
    payload.write_bytes(bytes([0xAA]) * 8192)
    small = tmp_path / "b.prg"
    small.write_bytes(bytes([0xBB]) * 16)
    source = tmp_path / "one.fds"
    source.write_bytes(blank_image(sides=1, headered=False, formatted=True))
    first = tmp_path / "first.fds"
    second = tmp_path / "second.fds"
    runner.invoke(
        app, ["insert", str(source), "-o", str(first), "--file", str(payload), "--name", "BIG"]
    )
    runner.invoke(
        app, ["insert", str(first), "-o", str(second), "--file", str(small), "--name", "SMALL"]
    )

    data = json.loads(runner.invoke(app, ["layout", str(second), "--json"]).stdout)

    assert data["sides"][0]["reorder_saving_bytes"] > 0
    assert [entry["name"] for entry in data["sides"][0]["files"]] == ["BIG", "SMALL"]


def test_layout_prints_the_reorder_note(tmp_path: Path) -> None:
    big = tmp_path / "a.prg"
    big.write_bytes(bytes([0xAA]) * 8192)
    small = tmp_path / "b.prg"
    small.write_bytes(bytes([0xBB]) * 16)
    source = tmp_path / "one.fds"
    source.write_bytes(blank_image(sides=1, headered=False, formatted=True))
    first = tmp_path / "first.fds"
    second = tmp_path / "second.fds"
    runner.invoke(
        app, ["insert", str(source), "-o", str(first), "--file", str(big), "--name", "BIG"]
    )
    runner.invoke(
        app, ["insert", str(first), "-o", str(second), "--file", str(small), "--name", "SMALL"]
    )

    result = runner.invoke(app, ["layout", str(second)])

    assert "measurement rather than a recommendation" in result.stdout


def test_merge_joins_two_disks_into_one_image(tmp_path: Path) -> None:
    first = tmp_path / "disk1.fds"
    second = tmp_path / "disk2.fds"
    first.write_bytes(blank_image(sides=2, headered=False, formatted=True, game_name="ON1"))
    second.write_bytes(blank_image(sides=2, headered=False, formatted=True, game_name="ON2"))
    output = tmp_path / "set.fds"

    result = runner.invoke(app, ["merge", str(first), str(second), "-o", str(output)])

    assert result.exit_code == 0
    assert "4 sides" in result.stdout
    assert len(output.read_bytes()) == 4 * SIDE_SIZE


def test_merge_refuses_a_set_larger_than_a_disk_holder(tmp_path: Path) -> None:
    big = tmp_path / "big.fds"
    big.write_bytes(blank_image(sides=8, headered=False, formatted=True))
    small = tmp_path / "small.fds"
    small.write_bytes(blank_image(sides=2, headered=False, formatted=True))

    result = runner.invoke(app, ["merge", str(big), str(small), "-o", str(tmp_path / "out.fds")])

    assert result.exit_code == 1
    assert "at most 8 sides" in result.stdout


def test_merge_can_write_a_qd(tmp_path: Path) -> None:
    first = tmp_path / "a.fds"
    first.write_bytes(blank_image(sides=1, headered=False, formatted=True))
    output = tmp_path / "set.qd"

    result = runner.invoke(app, ["merge", str(first), "-o", str(output)])

    assert result.exit_code == 0
    assert output.exists()


def test_unmerge_writes_one_file_per_disk(tmp_path: Path) -> None:
    first = tmp_path / "disk1.fds"
    second = tmp_path / "disk2.fds"
    first.write_bytes(blank_image(sides=2, headered=False, formatted=True, game_name="ON1"))
    second.write_bytes(blank_image(sides=2, headered=False, formatted=True, game_name="ON2"))
    merged = tmp_path / "set.fds"
    runner.invoke(app, ["merge", str(first), str(second), "-o", str(merged)])
    out = tmp_path / "split"

    result = runner.invoke(app, ["unmerge", str(merged), "-d", str(out)])

    assert result.exit_code == 0
    written = sorted(path.name for path in out.iterdir())
    assert written == ["set (Disk 1).fds", "set (Disk 2).fds"]


def test_unmerge_refuses_to_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "one.fds"
    source.write_bytes(blank_image(sides=2, headered=False, formatted=True))
    out = tmp_path / "split"
    runner.invoke(app, ["unmerge", str(source), "-d", str(out)])

    result = runner.invoke(app, ["unmerge", str(source), "-d", str(out)])

    assert result.exit_code == 1
    assert "pass --force" in result.stdout


def test_unmerge_reports_a_side_without_a_disk_number(tmp_path: Path) -> None:
    source = tmp_path / "blank.fds"
    source.write_bytes(blank_image(sides=1, headered=False, formatted=False))

    result = runner.invoke(app, ["unmerge", str(source), "-d", str(tmp_path / "out")])

    assert "FDS017" in result.stdout


def test_unmerge_writes_qd_parts_from_a_qd(tmp_path: Path) -> None:
    plain = tmp_path / "one.fds"
    plain.write_bytes(blank_image(sides=2, headered=False, formatted=True))
    source = tmp_path / "one.qd"
    runner.invoke(app, ["convert", str(plain), "-o", str(source)])
    out = tmp_path / "split"

    runner.invoke(app, ["unmerge", str(source), "-d", str(out)])

    assert [path.suffix for path in out.iterdir()] == [".qd"]


def test_merge_keeps_a_header_when_asked(tmp_path: Path) -> None:
    source = tmp_path / "one.fds"
    source.write_bytes(blank_image(sides=2, headered=False, formatted=True))
    output = tmp_path / "set.fds"

    runner.invoke(app, ["merge", str(source), "-o", str(output), "--header"])

    assert output.read_bytes()[:4] == b"FDS\x1a"


def test_boot_reports_a_side_that_needs_a_bypass(single_side: Path) -> None:
    result = runner.invoke(app, ["boot", str(single_side)])

    assert result.exit_code == 0
    assert "BIOS error 20" in result.stdout


def test_boot_fails_an_unformatted_first_side(tmp_path: Path) -> None:
    source = tmp_path / "blank.fds"
    source.write_bytes(blank_image(sides=1, headered=False, formatted=False))

    result = runner.invoke(app, ["boot", str(source)])

    assert result.exit_code == 1
    assert "block 1 expected" in result.stdout


def test_boot_lists_the_files_it_loads(tmp_path: Path) -> None:
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

    result = runner.invoke(app, ["boot", str(built)])

    assert "boots" in result.stdout
    assert "at $2800" in result.stdout


def test_boot_can_emit_json(single_side: Path) -> None:
    payload = json.loads(runner.invoke(app, ["boot", str(single_side), "--json"]).stdout)

    assert payload["sides"][0]["verdict"] == "needs_bypass"
    assert payload["sides"][0]["error"] == 0x20


def test_insert_accepts_a_kind_by_name(tmp_path: Path) -> None:
    payload = tmp_path / "chr.bin"
    payload.write_bytes(bytes(16))
    source = tmp_path / "one.fds"
    source.write_bytes(blank_image(sides=1, headered=False, formatted=True))
    built = tmp_path / "built.fds"

    result = runner.invoke(
        app,
        [
            "insert",
            str(source),
            "-o",
            str(built),
            "--file",
            str(payload),
            "--name",
            "CHR",
            "--address",
            "0000",
            "--kind",
            "character",
        ],
    )

    assert result.exit_code == 0
    assert "character" in runner.invoke(app, ["ls", str(built)]).stdout


def _known_bios(monkeypatch: pytest.MonkeyPatch) -> bytes:
    data = bytes([0x5A]) * firmware.BIOS_SIZE
    crc = f"{zlib.crc32(data):08x}"
    monkeypatch.setattr(
        firmware,
        "KNOWN_REVISIONS",
        {crc: firmware.Revision(name="Rev 01A", crc32=crc, sha1="0" * 40, mame_name="x.bin")},
    )
    return data


def test_bios_identifies_a_known_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "disksys.rom"
    source.write_bytes(_known_bios(monkeypatch))

    result = runner.invoke(app, ["bios", str(source)])

    assert result.exit_code == 0
    assert "Rev 01A" in result.stdout
    assert "fceux    accepts it" in result.stdout


def test_bios_extracts_from_a_wrapped_dump(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    known = _known_bios(monkeypatch)
    source = tmp_path / "bios.nes"
    source.write_bytes(bytes(0x6000) + known + bytes(0x2000))
    output = tmp_path / "disksys.rom"

    result = runner.invoke(app, ["bios", str(source), "--extract", str(output)])

    assert result.exit_code == 0
    assert "offset 0x6000" in result.stdout
    assert output.read_bytes() == known


def test_bios_reports_an_unknown_file(tmp_path: Path) -> None:
    source = tmp_path / "odd.rom"
    source.write_bytes(bytes(0x2000))

    result = runner.invoke(app, ["bios", str(source)])

    assert result.exit_code == 1
    assert "unknown" in result.stdout


def test_bios_refuses_to_extract_nothing(tmp_path: Path) -> None:
    source = tmp_path / "odd.rom"
    source.write_bytes(bytes(0xA000))

    result = runner.invoke(app, ["bios", str(source), "--extract", str(tmp_path / "out.rom")])

    assert result.exit_code == 1
    assert "no known BIOS" in result.stdout


def test_bios_reports_a_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["bios", str(tmp_path / "nope.rom")])

    assert result.exit_code == 1


def test_bios_can_emit_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "disksys.rom"
    source.write_bytes(_known_bios(monkeypatch))

    payload = json.loads(runner.invoke(app, ["bios", str(source), "--json"]).stdout)

    assert payload["revision"] == "Rev 01A"
    assert payload["emulators"]["mesen2"] == "accepts it"


def test_bios_reports_a_file_too_small_to_be_one(tmp_path: Path) -> None:
    source = tmp_path / "tiny.rom"
    source.write_bytes(bytes(100))

    result = runner.invoke(app, ["bios", str(source)])

    assert "crc32" not in result.stdout
    assert "rejects it" in result.stdout


def _game_with_a_file(tmp_path: Path, name: str = "Game") -> Path:
    payload = tmp_path / "main.prg"
    payload.write_bytes(bytes([0xAA]) * 8)
    source = tmp_path / "blank.fds"
    source.write_bytes(blank_image(sides=2, headered=False, formatted=True))
    built = tmp_path / f"{name}.fds"
    runner.invoke(
        app, ["insert", str(source), "-o", str(built), "--file", str(payload), "--name", "MAIN"]
    )
    runner.invoke(
        app,
        [
            "insert",
            str(built),
            "-o",
            str(built),
            "--file",
            str(payload),
            "--name",
            "MAIN",
            "--side",
            "1",
            "--force",
        ],
    )
    return built


def test_export_writes_a_headerless_image_for_the_nt_mini(tmp_path: Path) -> None:
    source = _game_with_a_file(tmp_path)
    card = tmp_path / "card"

    result = runner.invoke(app, ["export", str(source), "--target", "nt-mini", "-d", str(card)])

    assert result.exit_code == 0
    assert len((card / "Game.fds").read_bytes()) == 2 * SIDE_SIZE


def test_export_places_the_bios(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _game_with_a_file(tmp_path)
    bios_file = tmp_path / "bios.bin"
    bios_file.write_bytes(_known_bios(monkeypatch))
    card = tmp_path / "card"

    runner.invoke(
        app,
        ["export", str(source), "--target", "mister", "-d", str(card), "--bios", str(bios_file)],
    )

    assert (card / "boot0.rom").exists()


def test_export_warns_about_a_known_swap_exception(tmp_path: Path) -> None:
    source = _game_with_a_file(tmp_path, name="Doremikko (Japan)")

    result = runner.invoke(
        app, ["export", str(source), "--target", "nt-mini", "-d", str(tmp_path / "card")]
    )

    assert "automatic side swap" in result.stdout


def test_export_refuses_to_overwrite(tmp_path: Path) -> None:
    source = _game_with_a_file(tmp_path)
    card = tmp_path / "card"
    runner.invoke(app, ["export", str(source), "--target", "nt-mini", "-d", str(card)])

    result = runner.invoke(app, ["export", str(source), "--target", "nt-mini", "-d", str(card)])

    assert result.exit_code == 1
    assert "pass --force" in result.stdout


def test_export_reports_a_missing_bios(tmp_path: Path) -> None:
    source = _game_with_a_file(tmp_path)

    result = runner.invoke(
        app,
        [
            "export",
            str(source),
            "--target",
            "mister",
            "-d",
            str(tmp_path / "card"),
            "--bios",
            str(tmp_path / "nope.rom"),
        ],
    )

    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_export_refuses_a_bios_for_ares(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _game_with_a_file(tmp_path)
    bios_file = tmp_path / "bios.bin"
    bios_file.write_bytes(_known_bios(monkeypatch))

    result = runner.invoke(
        app,
        [
            "export",
            str(source),
            "--target",
            "ares",
            "-d",
            str(tmp_path / "out"),
            "--bios",
            str(bios_file),
        ],
    )

    assert result.exit_code == 1
    assert "does not take a BIOS" in result.stdout


def test_ares_files_round_trip_through_import(tmp_path: Path) -> None:
    source = _game_with_a_file(tmp_path)
    out = tmp_path / "ares"
    runner.invoke(app, ["export", str(source), "--target", "ares", "-d", str(out)])
    rebuilt = tmp_path / "rebuilt.fds"

    result = runner.invoke(
        app,
        [
            "import-ares",
            str(out / "Game" / "disk1.sideA"),
            str(out / "Game" / "disk1.sideB"),
            "-o",
            str(rebuilt),
        ],
    )

    assert result.exit_code == 0
    assert rebuilt.read_bytes() == source.read_bytes()


def test_import_ares_can_write_a_qd(tmp_path: Path) -> None:
    source = _game_with_a_file(tmp_path)
    out = tmp_path / "ares"
    runner.invoke(app, ["export", str(source), "--target", "ares", "-d", str(out)])

    result = runner.invoke(
        app,
        ["import-ares", str(out / "Game" / "disk1.sideA"), "-o", str(tmp_path / "one.qd")],
    )

    assert result.exit_code == 0


def test_import_ares_reports_a_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["import-ares", str(tmp_path / "nope"), "-o", str(tmp_path / "x.fds")]
    )

    assert result.exit_code == 1


def test_import_ares_refuses_a_file_of_the_wrong_size(tmp_path: Path) -> None:
    bad = tmp_path / "disk1.sideA"
    bad.write_bytes(bytes(10))

    result = runner.invoke(app, ["import-ares", str(bad), "-o", str(tmp_path / "x.fds")])

    assert result.exit_code == 1
    assert "73728" in result.stdout


def test_a_sharp_mz_disk_is_refused_by_name(tmp_path: Path) -> None:
    source = tmp_path / "mz.qd"
    source.write_bytes(b"-QD format-" + b"\xff" * 5 + bytes(81920))

    result = runner.invoke(app, ["info", str(source)])

    assert result.exit_code == 1
    assert "Sharp MZ Quick Disk image in QDF form, not a Famicom" in result.stdout


def test_dump_keeps_the_drives_pulse_classes(
    single_side: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attach(monkeypatch, single_side)

    result = runner.invoke(
        app,
        ["dump", "-o", str(tmp_path / "dump.fds"), "--raw", str(tmp_path / "raw")],
    )

    assert "packed pulse classes" in result.stdout
    assert list((tmp_path / "raw").glob("*.raw03"))


def test_dump_keeps_the_fdsstick_captures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class CapturingStick(FdsStick):
        def __init__(self, disk: Disk) -> None:
            self._drive = SimulatedDrive(disk)
            self._captures = [b"\\x55" * 8]

        def status(self):  # noqa: ANN202
            return self._drive.status()

        def read_side(self, side: int):  # noqa: ANN202
            return self._drive.read_side(side)

    disk, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True))

    def open_capturing() -> CapturingStick:
        return CapturingStick(disk)

    monkeypatch.setattr(hardware_cmds, "open_fdsstick", open_capturing)

    result = runner.invoke(
        app,
        ["dump", "-o", str(tmp_path / "dump.fds"), "--raw", str(tmp_path / "raw")],
    )

    assert (tmp_path / "raw" / "dump.read01.raw03").read_bytes() == b"\\x55" * 8
    assert "packed pulse classes" in result.stdout


def test_doctor_reports_the_installation() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "fdstoolkit" in result.stdout
    assert "dat cache" in result.stdout


def test_doctor_can_emit_json() -> None:
    payload = json.loads(runner.invoke(app, ["doctor", "--json"]).stdout)

    assert payload["healthy"] is True
    assert {check["name"] for check in payload["checks"]} >= {"fdstoolkit", "python", "dat cache"}


def test_doctor_fails_on_an_unhealthy_installation(monkeypatch: pytest.MonkeyPatch) -> None:
    unhealthy = DoctorReport(checks=(Check("python", CheckStatus.FAILED, "3.10.0"),))
    monkeypatch.setattr(inspect_cmds, "diagnose", lambda: unhealthy)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "[failed]" in result.stdout


def test_web_starts_the_application(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[tuple[str, int]] = []

    def fake_server() -> tuple[object, object]:
        def run(built: object, *, host: str, port: int) -> None:
            del built
            started.append((host, port))

        def build() -> object:
            return object()

        return run, build

    monkeypatch.setattr(hardware_cmds, "web_server", fake_server)

    result = runner.invoke(app, ["web", "--port", "9123", "--no-open"])

    assert result.exit_code == 0
    assert started == [("127.0.0.1", 9123)]


def test_web_says_which_extra_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_server() -> tuple[object, object]:
        raise ImportError

    monkeypatch.setattr(hardware_cmds, "web_server", no_server)

    result = runner.invoke(app, ["web"])

    assert result.exit_code == 1
    assert "brew install" in result.stdout


def test_the_web_server_loader_returns_a_runner_and_a_factory() -> None:
    run, build = hardware_cmds.web_server()

    assert callable(run)
    assert callable(build)


def test_a_drive_that_returned_no_capture_says_so(tmp_path: Path) -> None:
    drive = FdsStick(HidApiTransport(FakeFdsStick()))

    hardware_cmds.keep_captures(drive, tmp_path, stem="d")

    assert not list(tmp_path.iterdir())


def test_dump_asks_the_operator_to_turn_the_disk_over(
    image: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OneFace:
        selects_sides = False

        def __init__(self, disk: Disk) -> None:
            self._inner = SimulatedDrive(disk)
            self.facing = 0

        def status(self):  # noqa: ANN202
            return self._inner.status()

        def read_side(self, side: int):  # noqa: ANN202, ARG002
            return self._inner.read_side(self.facing)

    disk, _, _, _ = common.decode_image(image)
    drive = OneFace(disk)

    def open_one_face(*args: object, **kwargs: object) -> OneFace:
        del args, kwargs
        return drive

    def flipped(message: str) -> bool:
        del message
        drive.facing = 1
        return True

    monkeypatch.setattr(hardware_cmds, "open_drive", open_one_face)
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.typer.confirm", flipped)

    result = runner.invoke(
        app,
        ["dump", "-o", str(tmp_path / "d.fds"), "--sides", "2"],
    )

    assert result.exit_code == 0


def test_surface_names_every_class_of_failing_block(
    single_side: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = SurfaceReport(
        passes=(
            PatternPass(
                0x00, verified=False, mismatched_blocks=((0, 4), (0, 9)), grade=Grade.FAILED
            ),
            PatternPass(0xFF, verified=False, mismatched_blocks=((0, 4),), grade=Grade.FAILED),
            PatternPass(0xAA, verified=True, mismatched_blocks=(), grade=Grade.CLEAN),
        ),
        coverage=1.0,
        data_bytes=59145,
        finish=Finish.ERASE,
        finish_verified=False,
    )

    def fixed_report(*args: object, **kwargs: object) -> SurfaceReport:
        del args, kwargs
        return report

    monkeypatch.setattr(hardware_cmds, "surface_test", fixed_report)

    attach(monkeypatch, single_side)

    result = runner.invoke(app, ["surface", "--yes"])

    assert "failed on more than one pattern" in result.stdout
    assert "marginal rather than dead" in result.stdout
    assert "rewriting refreshed them" in result.stdout
    assert "erased, with nothing the adapter can read" in result.stdout
    assert "which did not verify" in result.stdout
    assert result.exit_code == 1


def test_dump_can_be_told_the_disk_is_already_turned_over(
    image: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OneFace:
        selects_sides = False

        def __init__(self, disk: Disk) -> None:
            self._inner = SimulatedDrive(disk)
            self.facing = 0

        def status(self):  # noqa: ANN202
            return self._inner.status()

        def read_side(self, side: int):  # noqa: ANN202
            self.facing = side
            return self._inner.read_side(self.facing)

    disk, _, _, _ = common.decode_image(image)

    def open_one_face(*args: object, **kwargs: object) -> OneFace:
        del args, kwargs
        return OneFace(disk)

    monkeypatch.setattr(hardware_cmds, "open_drive", open_one_face)

    result = runner.invoke(
        app,
        ["dump", "-o", str(tmp_path / "d.fds"), "--sides", "2", "--yes"],
    )

    assert result.exit_code == 0
    assert "turn the disk over" in result.stdout


def test_web_opens_a_browser_unless_told_not_to(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []

    def fake_server() -> tuple[object, object]:
        def run(built: object, *, host: str, port: int) -> None:
            del built, host, port

        def build() -> object:
            return object()

        return run, build

    def remember(address: str) -> bool:
        opened.append(address)
        return True

    monkeypatch.setattr(hardware_cmds, "web_server", fake_server)
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.webbrowser.open", remember)

    result = runner.invoke(app, ["web", "--port", "9124"])

    assert result.exit_code == 0
    assert opened == ["http://127.0.0.1:9124"]


def _stub_web() -> tuple[Callable[..., None], Callable[[], object]]:
    def run(*_: object, **__: object) -> None:
        return None

    return run, object


def test_a_loopback_bind_says_nothing_leaves_this_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hardware_cmds, "_require_web", _stub_web)

    result = runner.invoke(app, ["web", "--host", "127.0.0.1", "--no-open"])

    assert "nothing leaves this machine" in result.stdout


def test_a_published_bind_warns_instead_of_claiming_privacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hardware_cmds, "_require_web", _stub_web)

    result = runner.invoke(app, ["web", "--host", PUBLISHED_HOST, "--no-open"])

    assert "nothing leaves this machine" not in result.stdout
    assert "there is no password" in result.stdout
