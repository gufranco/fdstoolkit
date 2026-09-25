from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path

import click
import pytest
from device import FakeFdsStick
from drive_double import FacingDrive, FaultPlan, SimulatedDrive
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
from fdstoolkit.drive.captures import Capture, load_bundle
from fdstoolkit.hardware import session
from fdstoolkit.hardware.fdsstick import FdsStick, HidApiTransport
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError
from fdstoolkit.hardware.session import Grade
from fdstoolkit.quality.surface import Finish, PatternPass, StopReason, SurfaceReport

runner = CliRunner()
STALL_CEILING = 0.05
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


def test_info_lists_files(tmp_path: Path) -> None:
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

    result = runner.invoke(app, ["info", str(source), "--files"])

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


def test_hash_writes_the_canonical_image(image: Path, tmp_path: Path) -> None:
    out = tmp_path / "canon.fds"

    result = runner.invoke(app, ["hash", str(image), "-o", str(out)])

    assert result.exit_code == 0
    assert out.stat().st_size == 2 * SIDE_SIZE
    assert "fdstoolkit:v1:content/v1:" in result.stdout
    assert f"wrote {out}" in result.stdout


def test_hash_refuses_to_overwrite_the_canonical_image(image: Path, tmp_path: Path) -> None:
    out = tmp_path / "canon.fds"
    out.write_bytes(b"x")

    result = runner.invoke(app, ["hash", str(image), "-o", str(out)])

    assert result.exit_code == 1
    assert out.read_bytes() == b"x"


def test_hash_accepts_a_profile(image: Path) -> None:
    result = runner.invoke(app, ["hash", str(image), "--profile", "data"])

    assert result.exit_code == 0
    assert "data/v1" in result.stdout


@pytest.mark.parametrize("suffix", [".fds", ".qd"])
def test_an_image_bundling_more_than_one_disk_is_refused(tmp_path: Path, suffix: str) -> None:
    bundle = tmp_path / f"bundle{suffix}"
    three = blank_image(sides=2, headered=False, formatted=True) + blank_image(
        sides=1, headered=False, formatted=True
    )
    bundle.write_bytes(
        three
        if suffix == ".fds"
        else encode_qd(fds.decode(three[: 2 * SIDE_SIZE])[0])[0]
        + encode_qd(fds.decode(three[2 * SIDE_SIZE :])[0])[0]
    )

    result = runner.invoke(app, ["info", str(bundle)])

    assert result.exit_code == 1
    assert "holds 3 sides" in result.output
    assert "one disk per image" in result.output


def test_blank_writes_the_reference_image(tmp_path: Path) -> None:
    out = tmp_path / "blank64.fds"

    result = runner.invoke(app, ["blank", "-o", str(out), "--sides", "1", "--header"])

    assert result.exit_code == 0
    assert out.stat().st_size == 16 + SIDE_SIZE


@pytest.mark.parametrize("command", ["blank", "dump", "surface"])
@pytest.mark.parametrize("sides", ["0", "3", "-1", "1.5", "2.0", "two"])
def test_a_side_count_other_than_one_or_two_is_refused(
    command: str, sides: str, tmp_path: Path
) -> None:
    output = ["-o", str(tmp_path / "x.fds")] if command != "surface" else []

    result = runner.invoke(app, [command, *output, "--sides", sides])

    assert result.exit_code == 2
    assert "--sides" in click.unstyle(result.output)


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


def attach(
    monkeypatch: pytest.MonkeyPatch,
    source: Path | None = None,
    plan: FaultPlan | None = None,
) -> SimulatedDrive:
    disk = None
    if source is not None:
        disk, _, _, _ = common.decode_image(source)
    drive = SimulatedDrive(disk, plan=plan) if plan else SimulatedDrive(disk)

    def opener() -> SimulatedDrive:
        return drive

    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", opener)
    return drive


class SilentStick:
    def __init__(self) -> None:
        self.released = threading.Event()

    def send_feature(self, data: bytes) -> None:
        del data

    def get_feature(self, report_id: int, length: int) -> bytes:
        del report_id, length
        self.released.wait()
        return b""

    def write_output(self, data: bytes) -> None:
        del data

    def close(self) -> None:
        self.released.set()


def test_a_dump_that_stalls_stops_and_writes_no_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    transport = SilentStick()
    monkeypatch.setattr(
        "fdstoolkit.cli.hardware_cmds.open_fdsstick",
        lambda: FdsStick(transport, ceiling=STALL_CEILING),
    )
    output = tmp_path / "stalled.fds"

    result = runner.invoke(app, ["dump", "-o", str(output)])

    assert result.exit_code == 1
    assert "reading side 0 did not finish within" in result.output
    assert not output.exists()
    assert transport.released.wait(1.0)


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


def test_dump_names_blocks_that_only_read_clean_on_a_re_read(
    image: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attach(monkeypatch, image, plan=FaultPlan(flaky_blocks={1: 2}))

    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.fds")])

    assert (
        "side 0: 1 block(s) only read clean on a re-read, so this disk is wearing" in result.stdout
    )


def test_dump_names_blocks_that_never_read_clean(
    image: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attach(monkeypatch, image, plan=FaultPlan(bad_crc_blocks=frozenset({1})))

    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.fds"), "--retries", "0"])

    assert result.exit_code == 1
    assert "side 0: 1 block(s) never read clean, blocks 1" in result.stdout


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


def attach_facing(monkeypatch: pytest.MonkeyPatch, source: Path) -> FacingDrive:
    disk, _, _, _ = common.decode_image(source)
    drive = FacingDrive(disk)
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: drive)
    return drive


def operator(drive: FacingDrive, *, turns: bool) -> Callable[..., Callable[[str], bool]]:
    def answer(message: str) -> bool:
        if "turn the disk over" in message:
            if turns:
                drive.turn(message)
            return turns
        return True

    def build(*, yes: bool) -> Callable[[str], bool]:
        del yes
        return answer

    return build


def test_write_turns_the_disk_once_for_a_two_side_image(
    image: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drive = attach_facing(monkeypatch, image)
    monkeypatch.setattr(hardware_cmds, "prompter", operator(drive, turns=True))

    result = runner.invoke(app, ["write", str(image)])

    assert result.exit_code == 0, result.stdout
    assert "  writing side 1" in result.stdout
    assert drive.turns == 1


def test_write_stops_when_the_turn_is_declined(
    image: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drive = attach_facing(monkeypatch, image)
    monkeypatch.setattr(hardware_cmds, "prompter", operator(drive, turns=False))

    result = runner.invoke(app, ["write", str(image)])

    assert result.exit_code == 1
    assert "declined to turn the disk over" in result.stdout


def test_a_prompt_answered_by_yes_is_still_shown(capsys: pytest.CaptureFixture[str]) -> None:
    ask = hardware_cmds.prompter(yes=True)

    answered = ask("turn the disk over")

    assert answered
    assert "turn the disk over" in capsys.readouterr().out


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
    listing = runner.invoke(app, ["info", str(out), "--files"])
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


def test_dump_reports_a_missing_fdsstick(tmp_path: Path) -> None:
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.fds")])

    assert result.exit_code == 1
    assert "FDSStick" in result.stdout or "hidapi" in result.stdout


def test_write_reports_a_missing_fdsstick(single_side: Path) -> None:
    result = runner.invoke(app, ["write", str(single_side), "--yes"])

    assert result.exit_code == 1
    assert "FDSStick" in result.stdout or "hidapi" in result.stdout


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


def test_info_lists_files_as_json(hidden_file_image: Path) -> None:
    payload = json.loads(
        runner.invoke(app, ["info", str(hidden_file_image), "--files", "--json"]).stdout
    )

    assert payload["files"][0]["name"] == "SECRET"
    assert payload["files"][0]["hidden"] is True


def test_info_marks_a_hidden_file(hidden_file_image: Path) -> None:
    result = runner.invoke(app, ["info", str(hidden_file_image), "--files"])

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


def test_blank_reports_an_invalid_game_name(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["blank", "-o", str(tmp_path / "b.fds"), "--game-name", "TOOLONG"],
    )

    assert result.exit_code == 1
    assert "three characters" in result.stdout


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
    assert "MAIN" in runner.invoke(app, ["info", str(out), "--files"]).stdout


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
    assert "character" in runner.invoke(app, ["info", str(built), "--files"]).stdout


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
            self._captures = [Capture(side=0, read=1, data=b"\\x55" * 8)]

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

    assert (tmp_path / "raw" / "side0.read01.raw03").read_bytes() == b"\\x55" * 8
    assert load_bundle(tmp_path / "raw").image == "dump.fds"
    assert "packed pulse classes" in result.stdout


def test_doctor_reports_the_installation() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "fdstoolkit" in result.stdout
    assert "dat cache" not in result.stdout


def test_doctor_can_emit_json() -> None:
    payload = json.loads(runner.invoke(app, ["doctor", "--json"]).stdout)

    assert payload["healthy"] is True
    assert {check["name"] for check in payload["checks"]} >= {"fdstoolkit", "python", "codec"}


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

    hardware_cmds.keep_captures(drive, tmp_path, image="d.fds")

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

        @property
        def captures(self):  # noqa: ANN202
            return self._inner.captures

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


def test_surface_says_why_it_stopped_and_that_the_finish_was_skipped(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attach(monkeypatch, single_side, plan=FaultPlan(writes_do_not_stick=True))

    result = runner.invoke(app, ["surface", "--yes", "--finish", "blank"])

    assert result.exit_code == 1
    assert f"stopped early: {StopReason.REFUSED.value}" in result.stdout
    assert "reads back exactly as it was before the write" in result.stdout
    assert "the finish was skipped because the test stopped early" in result.stdout


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
        finish_ran=True,
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

        @property
        def captures(self):  # noqa: ANN202
            return self._inner.captures

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


def ready_checks() -> tuple[Check, ...]:
    return (
        Check("hardware support", CheckStatus.OK, "hidapi is installed"),
        Check("fdsstick", CheckStatus.OK, "1 device(s) connected"),
    )


def absent_checks() -> tuple[Check, ...]:
    return (
        Check("hardware support", CheckStatus.OK, "hidapi is installed"),
        Check("fdsstick", CheckStatus.WARNING, "none connected at 16D0:0AAA"),
    )


def test_status_reports_a_ready_stick_and_what_it_cannot_say(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hardware_cmds, "hardware_checks", ready_checks)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "1 device(s) connected" in result.stdout
    assert "reports nothing about the disk itself" in result.stdout


def test_status_fails_and_marks_a_missing_stick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hardware_cmds, "hardware_checks", absent_checks)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "none connected at 16D0:0AAA [warning]" in result.stdout


def test_status_can_print_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hardware_cmds, "hardware_checks", absent_checks)

    result = runner.invoke(app, ["status", "--json"])

    payload = json.loads(result.stdout)
    assert result.exit_code == 1
    assert payload["ready"] is False
    assert [check["name"] for check in payload["checks"]] == ["hardware support", "fdsstick"]


def test_dump_recovers_a_failed_block_from_the_reads_it_kept(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attach(monkeypatch, single_side, plan=FaultPlan(bad_crc_blocks=frozenset({1})))

    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.fds"), "--retries", "2"])

    assert "side 0 block 1: recovered by a pulse vote across 3 reads" in result.stdout
    assert "grade marginal" in result.stdout
