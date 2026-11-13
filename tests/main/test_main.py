from __future__ import annotations

import json
import logging
import sys
import threading
import webbrowser
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import click
import pytest
import typer
from device import FakeFdsStick
from drive_double import FacingDrive, FaultPlan, SimulatedDrive
from fastapi import FastAPI
from hid_double import FakeHid, stick
from server_double import FakeUvicorn
from typer.testing import CliRunner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.calibration import LARGEST_FACTORY_SIDE, calibration_disk
from fdstoolkit.cli import common, hardware_cmds
from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds, qd
from fdstoolkit.codecs.qd import encode as encode_qd
from fdstoolkit.codecs.raw import encode_raw03
from fdstoolkit.core.blocks import Block, BlockKind, CrcStatus, FileKind
from fdstoolkit.core.disk import SIDE_SIZE, Disk, Side
from fdstoolkit.drive.captures import Capture, load_bundle, write_bundle
from fdstoolkit.edit.files import FileSpec, insert_file
from fdstoolkit.hardware.fdsstick import FdsStick, HidApiTransport
from fdstoolkit.hardware.ports import BlockRead, FaultKind, HardwareFaultError
from fdstoolkit.hardware.session import Grade
from fdstoolkit.quality.surface import (
    Finish,
    PatternPass,
    StopReason,
    SurfacePattern,
    SurfaceReport,
)

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


def test_convert_writes_a_qd(image: Path, tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "disk.qd"

    # Act
    result = runner.invoke(app, ["convert", str(image), "-o", str(out)])

    # Assert
    assert result.exit_code == 0
    assert out.stat().st_size == 2 * 65536


def test_convert_round_trips_back_to_fds(image: Path, tmp_path: Path) -> None:
    # Arrange
    as_qd = tmp_path / "disk.qd"
    back = tmp_path / "back.fds"
    runner.invoke(app, ["convert", str(image), "-o", str(as_qd)])

    # Act
    runner.invoke(app, ["convert", str(as_qd), "-o", str(back)])

    # Assert
    assert back.read_bytes() == image.read_bytes()


def test_convert_refuses_to_overwrite_without_force(image: Path, tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "taken.qd"
    out.write_bytes(b"existing")

    # Act
    result = runner.invoke(app, ["convert", str(image), "-o", str(out)])

    # Assert
    assert result.exit_code == 1
    assert out.read_bytes() == b"existing"


def test_convert_overwrites_when_forced(image: Path, tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "taken.qd"
    out.write_bytes(b"existing")

    # Act
    result = runner.invoke(app, ["convert", str(image), "-o", str(out), "--force"])

    # Assert
    assert result.exit_code == 0
    assert out.read_bytes() != b"existing"


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


@pytest.mark.parametrize("suffix", [".fds", ".qd"])
def test_an_image_bundling_more_than_one_disk_is_refused(tmp_path: Path, suffix: str) -> None:
    # Arrange
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

    # Act
    result = runner.invoke(app, ["info", str(bundle)])

    # Assert
    assert result.exit_code == 1
    assert "holds 3 sides" in result.output
    assert "one disk per image" in result.output


def test_blank_writes_the_reference_image(tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "blank64.fds"

    # Act
    result = runner.invoke(app, ["blank", "-o", str(out), "--sides", "1", "--header"])

    # Assert
    assert result.exit_code == 0
    assert out.stat().st_size == 16 + SIDE_SIZE


@pytest.mark.parametrize("command", ["blank", "dump", "surface"])
@pytest.mark.parametrize("sides", ["0", "3", "-1", "1.5", "2.0", "two"])
def test_a_side_count_other_than_one_or_two_is_refused(
    command: str, sides: str, tmp_path: Path
) -> None:
    # Arrange
    output = ["-o", str(tmp_path / "x.fds")] if command != "surface" else []

    # Act
    result = runner.invoke(app, [command, *output, "--sides", sides])

    # Assert
    assert result.exit_code == 2
    assert "--sides" in click.unstyle(result.output)


def test_blank_can_write_a_formatted_disk(tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "formatted.fds"

    # Act
    runner.invoke(app, ["blank", "-o", str(out), "--sides", "2", "--formatted"])

    # Assert
    assert runner.invoke(app, ["verify", str(out)]).exit_code == 0


def test_a_missing_file_is_reported_without_a_traceback(tmp_path: Path) -> None:
    # Arrange
    arguments = ["info", str(tmp_path / "nope.fds")]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_an_unknown_extension_is_reported(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "disk.bin"
    path.write_bytes(bytes(SIDE_SIZE))

    # Act
    result = runner.invoke(app, ["info", str(path)])

    # Assert
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

    def write_output(self, data: bytes) -> int:
        return len(data)

    def close(self) -> None:
        self.released.set()


def test_a_dump_that_stalls_stops_and_writes_no_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    transport = SilentStick()
    monkeypatch.setattr(
        "fdstoolkit.cli.hardware_cmds.open_fdsstick",
        lambda: FdsStick(transport, ceiling=STALL_CEILING),
    )
    output = tmp_path / "stalled.fds"

    # Act
    result = runner.invoke(app, ["dump", "-o", str(output)])

    # Assert
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
    # Arrange
    attach(monkeypatch, image)
    out = tmp_path / "dump.fds"

    # Act
    result = runner.invoke(app, ["dump", "-o", str(out)])

    # Assert
    assert result.exit_code == 0
    assert "grade clean" in result.stdout
    assert out.stat().st_size == SIDE_SIZE


def test_dump_to_a_qd_file_writes_quick_disk_bytes_with_the_checksums_read(
    image: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attach(monkeypatch, image, plan=FaultPlan(bad_crc_blocks=frozenset({1})))
    out = tmp_path / "dump.qd"
    result = runner.invoke(app, ["dump", "-o", str(out), "--retries", "0"])

    # Act
    disk, findings = qd.decode(out.read_bytes())

    # Assert
    assert result.exit_code == 1
    assert out.stat().st_size == qd.SIDE_SIZE
    assert [block.crc_status for block in disk.sides[0].blocks] == [
        CrcStatus.VALID,
        CrcStatus.MISMATCH,
    ]
    assert findings != ()


def test_dump_refuses_an_output_it_cannot_encode_before_reading(
    image: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach(monkeypatch, image)

    # Act
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.bin")])

    # Assert
    assert result.exit_code == 1
    assert "expected a .fds, .qd or .srm file" in result.stdout
    assert drive.read_count == 0


def test_dump_names_blocks_that_only_read_clean_on_a_re_read(
    image: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attach(monkeypatch, image, plan=FaultPlan(flaky_blocks={1: 2}))

    # Act
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.fds")])

    # Assert
    assert (
        "side 0: 1 block(s) only read clean on a re-read, so this disk is wearing" in result.stdout
    )


def test_dump_names_blocks_that_never_read_clean(
    image: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attach(monkeypatch, image, plan=FaultPlan(bad_crc_blocks=frozenset({1})))

    # Act
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.fds"), "--retries", "0"])

    # Assert
    assert result.exit_code == 1
    assert "side 0: 1 block(s) never read clean, blocks 1" in result.stdout


def test_dump_refuses_when_no_stick_is_attached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    detach(monkeypatch)

    # Act
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.fds")])

    # Assert
    assert result.exit_code == 1
    assert "FDSStick" in result.stdout


def test_dump_can_repeat_a_read_to_check_stability(
    image: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attach(monkeypatch, image)
    out = tmp_path / "dump.fds"

    # Act
    result = runner.invoke(app, ["dump", "-o", str(out), "--passes", "3"])

    # Assert
    assert result.exit_code == 0


def test_write_verifies_by_reading_back(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attach(monkeypatch, single_side)
    backup = tmp_path / "before.fds"

    # Act
    result = runner.invoke(
        app,
        ["write", str(single_side), "--backup", str(backup), "--yes"],
    )

    # Assert
    assert result.exit_code == 0
    assert "verified True" in result.stdout
    assert backup.exists()


def long_side_image(single_side: Path, tmp_path: Path) -> Path:
    disk, _, _, _ = common.decode_image(single_side)
    longer = insert_file(
        disk,
        side=0,
        spec=FileSpec(
            name="LONG", address=0x6000, kind=FileKind.PROGRAM, data=bytes(LARGEST_FACTORY_SIDE)
        ),
    )
    path = tmp_path / "long.fds"
    path.write_bytes(fds.encode(longer, headered=False)[0])
    return path


def test_write_refuses_a_side_longer_than_any_factory_side(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach(monkeypatch, single_side)

    # Act
    result = runner.invoke(app, ["write", str(long_side_image(single_side, tmp_path)), "--yes"])

    # Assert
    assert result.exit_code == 1
    assert "Pass --long-side to write it anyway" in result.stdout
    assert drive.write_count == 0


def test_write_writes_a_long_side_when_told_to(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach(monkeypatch, single_side)
    image = long_side_image(single_side, tmp_path)

    # Act
    result = runner.invoke(app, ["write", str(image), "--yes", "--long-side"])

    # Assert
    assert result.exit_code == 0
    assert drive.write_count == 1


def test_write_stops_when_the_confirmation_is_declined(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attach(monkeypatch, single_side)

    # Act
    result = runner.invoke(app, ["write", str(single_side)], input="n\n")

    # Assert
    assert result.exit_code == 1
    assert "declined" in result.stdout


def attach_facing(monkeypatch: pytest.MonkeyPatch, source: Path) -> FacingDrive:
    disk, _, _, _ = common.decode_image(source)
    drive = FacingDrive(disk)
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: drive)
    return drive


def operator(drive: FacingDrive, *, turns: bool) -> Callable[..., bool]:
    def answer(message: str, **_: object) -> bool:
        if "turn the disk over" in message:
            if turns:
                drive.turn(message)
            return turns
        return True

    return answer


def test_write_turns_the_disk_once_for_a_two_side_image(
    image: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach_facing(monkeypatch, image)
    monkeypatch.setattr(typer, "confirm", operator(drive, turns=True))

    # Act
    result = runner.invoke(app, ["write", str(image)])

    # Assert
    assert result.exit_code == 0, result.output
    assert "  writing side 1" in result.stderr
    assert drive.turns == 1


def test_write_stops_when_the_turn_is_declined(
    image: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach_facing(monkeypatch, image)
    monkeypatch.setattr(typer, "confirm", operator(drive, turns=False))

    # Act
    result = runner.invoke(app, ["write", str(image)])

    # Assert
    assert result.exit_code == 1
    assert "declined to turn the disk over" in result.stdout


def test_a_prompt_answered_by_yes_is_still_shown(capsys: pytest.CaptureFixture[str]) -> None:
    # Arrange
    ask = hardware_cmds.prompter(yes=True)

    # Act
    answered = ask("turn the disk over")

    # Assert
    assert answered
    assert "turn the disk over" in capsys.readouterr().err


def test_extract_writes_every_file(tmp_path: Path) -> None:
    # Arrange
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

    # Act
    result = runner.invoke(app, ["extract", str(source), "-d", str(out)])

    # Assert
    assert result.exit_code == 0
    assert (out / "side0-00-HELLO.bin").read_bytes() == bytes([0xAB]) * 4


def test_insert_adds_a_file(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "payload.bin"
    payload.write_bytes(bytes([0x42]) * 32)
    out = tmp_path / "with-new.fds"
    arguments = [
        "insert",
        str(single_side),
        "-o",
        str(out),
        "--file",
        str(payload),
        "--name",
        "NEW",
    ]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    listing = runner.invoke(app, ["info", str(out), "--files"])
    assert "NEW" in listing.stdout


def test_insert_reports_a_name_that_is_too_long(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"\x01")

    # Act
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

    # Assert
    assert result.exit_code == 1
    assert "eight characters" in result.stdout


def test_patch_applies_an_ips(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    patch = tmp_path / "rename.ips"
    patch.write_bytes(
        b"PATCH" + (0x10).to_bytes(3, "big") + (3).to_bytes(2, "big") + b"ZEL" + b"EOF"
    )
    out = tmp_path / "patched.fds"

    # Act
    result = runner.invoke(
        app,
        ["patch", str(single_side), "--patch", str(patch), "-o", str(out)],
    )

    # Assert
    assert result.exit_code == 0
    assert "applied ips" in result.stdout
    assert (
        json.loads(runner.invoke(app, ["info", str(out), "--json"]).stdout)["sides"][0]["game_name"]
        == "ZEL"
    )


def test_patch_refuses_an_ips_cut_short_with_a_message(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    patch = tmp_path / "short.ips"
    patch.write_bytes(b"PATCH" + (0).to_bytes(3, "big") + (0).to_bytes(2, "big") + b"\x00")
    out = tmp_path / "patched.fds"

    # Act
    result = runner.invoke(app, ["patch", str(single_side), "--patch", str(patch), "-o", str(out)])

    # Assert
    assert result.exit_code == 1
    assert "the patch ends inside a record at byte 10" in result.stdout
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_patch_reports_a_missing_patch_file(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    arguments = [
        "patch",
        str(single_side),
        "--patch",
        str(tmp_path / "nope.ips"),
        "-o",
        str(tmp_path / "o.fds"),
    ]

    # Act
    result = runner.invoke(
        app,
        arguments,
    )

    # Assert
    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_patch_reports_an_unknown_format(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    patch = tmp_path / "bad.ips"
    patch.write_bytes(b"nonsense")

    # Act
    result = runner.invoke(
        app,
        ["patch", str(single_side), "--patch", str(patch), "-o", str(tmp_path / "o.fds")],
    )

    # Assert
    assert result.exit_code == 1
    assert "unknown patch format" in result.stdout


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


def test_dump_reports_a_missing_fdsstick(tmp_path: Path) -> None:
    # Arrange
    arguments = ["dump", "-o", str(tmp_path / "dump.fds")]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 1
    assert "FDSStick" in result.stdout or "hidapi" in result.stdout


def test_write_reports_a_missing_fdsstick(single_side: Path) -> None:
    # Arrange
    arguments = ["write", str(single_side), "--yes"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 1
    assert "FDSStick" in result.stdout or "hidapi" in result.stdout


def test_diff_reports_identical_images(single_side: Path) -> None:
    # Arrange
    arguments = ["diff", str(single_side), str(single_side)]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    assert "identical" in result.stdout


def test_diff_reports_a_difference(single_side: Path, image: Path) -> None:
    # Arrange
    arguments = ["diff", str(single_side), str(image)]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 1
    assert "side count" in result.stdout


def test_consensus_merges_identical_dumps(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "merged.fds"

    # Act
    result = runner.invoke(
        app,
        ["consensus", str(single_side), str(single_side), "-o", str(out)],
    )

    # Assert
    assert result.exit_code == 0
    assert out.read_bytes() == single_side.read_bytes()


def test_consensus_needs_two_dumps(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    arguments = ["consensus", str(single_side), "-o", str(tmp_path / "m.fds")]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
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


def test_convert_reports_a_side_that_will_not_fit_the_target(tmp_path: Path) -> None:
    # Arrange
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

    # Act
    result = runner.invoke(app, ["convert", str(source), "-o", str(out)])

    # Assert
    assert result.exit_code == 1
    assert "FDS011" in result.stdout


def test_extract_refuses_to_overwrite(hidden_file_image: Path, tmp_path: Path) -> None:
    # Arrange
    target = tmp_path / "files"
    target.mkdir()
    (target / "side0-00-SECRET.bin").write_bytes(b"old")

    # Act
    result = runner.invoke(app, ["extract", str(hidden_file_image), "-d", str(target)])

    # Assert
    assert result.exit_code == 1
    assert "--force" in result.stdout


def test_insert_reports_a_missing_file(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    arguments = [
        "insert",
        str(single_side),
        "-o",
        str(tmp_path / "out.fds"),
        "--file",
        str(tmp_path / "nope.bin"),
        "--name",
        "NEW",
    ]

    # Act
    result = runner.invoke(
        app,
        arguments,
    )

    # Assert
    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_insert_can_write_a_qd(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "payload.bin"
    payload.write_bytes(bytes([0x42]) * 8)
    out = tmp_path / "with-new.qd"

    # Act
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

    # Assert
    assert result.exit_code == 0
    assert out.stat().st_size == 65536


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


def test_dump_reports_unstable_blocks(
    image: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attach(monkeypatch, image)

    # Act
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "d.fds"), "--passes", "2"])

    # Assert
    assert result.exit_code == 0


def test_a_recovered_block_does_not_hide_that_the_passes_disagreed(
    image: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attach(
        monkeypatch,
        image,
        plan=FaultPlan(bad_crc_blocks=frozenset({1}), unstable_blocks=frozenset({0})),
    )

    # Act
    result = runner.invoke(
        app, ["dump", "-o", str(tmp_path / "d.fds"), "--passes", "3", "--retries", "0"]
    )

    # Assert
    assert "recovered" in result.stdout
    assert "grade unstable" in result.stdout
    assert result.exit_code == 1


def test_dump_reports_a_drive_fault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    empty = tmp_path / "empty.fds"
    empty.write_bytes(bytes(SIDE_SIZE))
    attach(monkeypatch, empty)

    # Act
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "d.fds"), "--sides", "2"])

    # Assert
    assert result.exit_code == 1


def test_diff_can_emit_json(single_side: Path) -> None:
    # Arrange
    expected = True

    # Act
    payload = json.loads(
        runner.invoke(app, ["diff", str(single_side), str(single_side), "--json"]).stdout
    )

    # Assert
    assert payload["identical"] is expected


def test_diff_lists_the_blocks_that_differ(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    other = tmp_path / "other.fds"
    data = bytearray(single_side.read_bytes())
    data[57] = 0x01
    other.write_bytes(bytes(data))

    # Act
    result = runner.invoke(app, ["diff", str(single_side), str(other)])

    # Assert
    assert result.exit_code == 1
    assert "side 0 block" in result.stdout


def test_consensus_reports_a_disagreement(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    other = tmp_path / "other.fds"
    data = bytearray(single_side.read_bytes())
    data[57] = 0x01
    other.write_bytes(bytes(data))

    # Act
    result = runner.invoke(
        app,
        ["consensus", str(single_side), str(other), "-o", str(tmp_path / "merged.fds")],
    )

    # Assert
    assert result.exit_code == 1
    assert "disagree" in result.stdout


def test_blank_reports_an_invalid_game_name(tmp_path: Path) -> None:
    # Arrange
    arguments = ["blank", "-o", str(tmp_path / "b.fds"), "--game-name", "TOOLONG"]

    # Act
    result = runner.invoke(
        app,
        arguments,
    )

    # Assert
    assert result.exit_code == 1
    assert "three characters" in result.stdout


def test_dump_names_a_block_that_differs_between_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    source = tmp_path / "source.fds"
    source.write_bytes(blank_image(sides=1, headered=False, formatted=True))
    attach(monkeypatch, source, plan=FaultPlan(unstable_blocks=frozenset({1})))

    # Act
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "d.fds"), "--passes", "2"])

    # Assert
    assert "differs between passes" in result.stdout


def test_write_names_a_block_that_did_not_stick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    source = tmp_path / "source.fds"
    source.write_bytes(blank_image(sides=1, headered=False, formatted=True))
    attach(monkeypatch, source, plan=FaultPlan(unstable_blocks=frozenset({1})))

    # Act
    result = runner.invoke(app, ["write", str(source), "--yes"])

    # Assert
    assert "did not read back as written" in result.stdout


def test_insert_reports_a_finding_from_the_encoder(tmp_path: Path) -> None:
    # Arrange
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

    # Act
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

    # Assert
    assert "FDS011" in result.stdout


def test_build_writes_a_disk_from_a_manifest(tmp_path: Path) -> None:
    # Arrange
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

    # Act
    result = runner.invoke(app, ["build", str(manifest), "-o", str(out)])

    # Assert
    assert result.exit_code == 0
    assert runner.invoke(app, ["verify", str(out), "--strict"]).exit_code == 0
    assert "MAIN" in runner.invoke(app, ["info", str(out), "--files"]).stdout


def test_build_reports_a_missing_manifest(tmp_path: Path) -> None:
    # Arrange
    arguments = ["build", str(tmp_path / "nope.json"), "-o", str(tmp_path / "out.fds")]

    # Act
    result = runner.invoke(
        app,
        arguments,
    )

    # Assert
    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_build_reports_a_manifest_that_does_not_parse(tmp_path: Path) -> None:
    # Arrange
    manifest = tmp_path / "bad.json"
    manifest.write_text(json.dumps({"game_name": "SMB", "sides": []}), encoding="utf-8")

    # Act
    result = runner.invoke(app, ["build", str(manifest), "-o", str(tmp_path / "out.fds")])

    # Assert
    assert result.exit_code == 1
    assert "at least one side" in result.stdout


def test_set_changes_a_field(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "renamed.fds"
    arguments = ["set", str(single_side), "-o", str(out), "--set", "game_name=ZEL"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    assert "game_name: SMB -> ZEL" in result.stdout
    payload = json.loads(runner.invoke(app, ["info", str(out), "--json"]).stdout)
    assert payload["sides"][0]["game_name"] == "ZEL"


def test_set_can_write_a_qd(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "renamed.qd"

    # Act
    result = runner.invoke(
        app,
        ["set", str(single_side), "-o", str(out), "--set", "game_version=2"],
    )

    # Assert
    assert result.exit_code == 0
    assert out.stat().st_size == 65536


def test_set_reports_an_unknown_field(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    arguments = ["set", str(single_side), "-o", str(tmp_path / "o.fds"), "--set", "colour=blue"]

    # Act
    result = runner.invoke(
        app,
        arguments,
    )

    # Assert
    assert result.exit_code == 1
    assert "unknown field" in result.stdout


def test_surface_grades_a_healthy_disk(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attach(monkeypatch, single_side)

    # Act
    result = runner.invoke(
        app,
        ["surface", "--yes", "--backup", str(tmp_path / "b.fds")],
    )

    # Assert
    assert result.exit_code == 0
    assert "grade clean" in result.stdout


def test_surface_stops_when_declined(single_side: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    attach(monkeypatch, single_side)

    # Act
    result = runner.invoke(app, ["surface"], input="n\n")

    # Assert
    assert result.exit_code == 1
    assert "declined" in result.stdout


def test_surface_closes_the_drive_when_declined(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach(monkeypatch, single_side)

    # Act
    runner.invoke(app, ["surface"], input="n\n")

    # Assert
    assert drive.closed


def test_surface_runs_without_a_backup(single_side: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    attach(monkeypatch, single_side)

    # Act
    result = runner.invoke(app, ["surface", "--yes"])

    # Assert
    assert result.exit_code == 0


def test_the_version_flag_prints_the_version() -> None:
    # Arrange
    arguments = ["--version"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    assert result.stdout.startswith("fdstoolkit ")


def test_the_help_lists_the_commands() -> None:
    # Arrange
    arguments = ["--help"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    assert "verify" in result.stdout


def test_dump_stops_cleanly_on_an_interrupt(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    disk, _, _, _ = common.decode_image(single_side)

    class Interrupted(SimulatedDrive):
        def read_side(self, side: int) -> Iterator[BlockRead]:
            del side
            raise KeyboardInterrupt

    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: Interrupted(disk))

    # Act
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "d.fds")])

    # Assert
    assert result.exit_code == 1
    assert "nothing was written" in result.stdout


def test_write_warns_when_an_interrupt_lands_mid_write(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    disk, _, _, _ = common.decode_image(single_side)

    class Interrupted(SimulatedDrive):
        def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
            del side, blocks
            raise KeyboardInterrupt

    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: Interrupted(disk))

    # Act
    result = runner.invoke(app, ["write", str(single_side), "--yes"])

    # Assert
    assert result.exit_code == 1
    assert "half written" in result.stdout


def test_diff_explains_two_identical_images(image: Path) -> None:
    # Arrange
    arguments = ["diff", str(image), str(image), "--explain"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    assert result.stdout.startswith("identical")


def test_diff_explains_a_changed_field(image: Path, tmp_path: Path) -> None:
    # Arrange
    other = tmp_path / "other.fds"
    runner.invoke(app, ["set", str(image), "-o", str(other), "--set", "game_version=2"])

    # Act
    result = runner.invoke(app, ["diff", str(image), str(other), "--explain"])

    # Assert
    assert result.exit_code == 1
    assert "different software" in result.stdout
    assert "game_version (identity): 0x00 against 0x02" in result.stdout


def test_diff_can_explain_as_json(image: Path, tmp_path: Path) -> None:
    # Arrange
    other = tmp_path / "other.fds"
    runner.invoke(app, ["set", str(image), "-o", str(other), "--set", "rewrite_count=3"])

    # Act
    payload = json.loads(
        runner.invoke(app, ["diff", str(image), str(other), "--explain", "--json"]).stdout
    )

    # Assert
    assert payload["same_software"]
    assert payload["fields"][0]["field"] == "rewrite_count"


def test_rebuild_reports_that_there_is_nothing_to_repair(image: Path, tmp_path: Path) -> None:
    # Arrange
    arguments = ["rebuild", str(image), "-o", str(tmp_path / "out.fds")]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    assert "nothing to repair" in result.stdout


def test_rebuild_drops_trailing_data(tmp_path: Path) -> None:
    # Arrange
    raw = bytearray(blank_image(sides=1, headered=False, formatted=True))
    raw[-4:] = b"junk"
    source = tmp_path / "tail.fds"
    source.write_bytes(bytes(raw))
    output = tmp_path / "clean.fds"

    # Act
    result = runner.invoke(app, ["rebuild", str(source), "-o", str(output)])

    # Assert
    assert "trailing byte(s) removed" in result.stdout
    assert output.read_bytes().endswith(bytes(4))


def test_rebuild_recomputes_checksums_in_a_qd(tmp_path: Path) -> None:
    # Arrange
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

    # Act
    result = runner.invoke(app, ["rebuild", str(source), "-o", str(output)])

    # Assert
    assert "checksum(s) recomputed" in result.stdout


def test_rebuild_refuses_two_conflicting_options(image: Path, tmp_path: Path) -> None:
    # Arrange
    arguments = [
        "rebuild",
        str(image),
        "-o",
        str(tmp_path / "out.fds"),
        "--reveal-hidden",
        "--drop-hidden",
    ]

    # Act
    result = runner.invoke(
        app,
        arguments,
    )

    # Assert
    assert result.exit_code == 1
    assert "either reveal or drop" in result.stdout


def test_consensus_prints_a_stability_map(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    other = tmp_path / "second.fds"
    other.write_bytes(single_side.read_bytes())
    output = tmp_path / "merged.fds"

    # Act
    result = runner.invoke(
        app, ["consensus", str(single_side), str(other), "-o", str(output), "--map"]
    )

    # Assert
    assert result.exit_code == 0
    assert "disk_info" in result.stdout
    assert "100.0%" in result.stdout


def test_diff_explains_a_file_difference(single_side: Path, tmp_path: Path) -> None:
    # Arrange
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

    # Act
    result = runner.invoke(app, ["diff", str(single_side), str(other), "--explain"])

    # Assert
    assert result.exit_code == 1
    assert "file 0 MAIN: added, 8 bytes" in result.stdout


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


def test_insert_accepts_a_kind_by_name(tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "chr.bin"
    payload.write_bytes(bytes(16))
    source = tmp_path / "one.fds"
    source.write_bytes(blank_image(sides=1, headered=False, formatted=True))
    built = tmp_path / "built.fds"

    # Act
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

    # Assert
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


def test_an_everdrive_save_is_read_as_a_headerless_image(tmp_path: Path) -> None:
    # Arrange
    source = tmp_path / "bram.srm"
    source.write_bytes(_game_with_a_file(tmp_path).read_bytes())

    # Act
    result = runner.invoke(app, ["info", str(source)])

    # Assert
    assert result.exit_code == 0
    assert "bram.srm: fds container, 2 side(s)" in result.stdout


def test_a_cartridge_save_named_srm_is_refused_with_the_reason(tmp_path: Path) -> None:
    # Arrange
    source = tmp_path / "Zelda.srm"
    source.write_bytes(bytes(8192))

    # Act
    result = runner.invoke(app, ["info", str(source)])

    # Assert
    assert result.exit_code == 1
    assert "Zelda.srm is not a Famicom Disk System save" in result.stdout
    assert "8192 bytes" in result.stdout


def test_a_disk_converts_to_an_everdrive_save(tmp_path: Path) -> None:
    # Arrange
    source = _game_with_a_file(tmp_path)
    output = tmp_path / "bram.srm"

    # Act
    result = runner.invoke(app, ["convert", str(source), "-o", str(output)])

    # Assert
    assert result.exit_code == 0
    assert output.read_bytes() == source.read_bytes()


def test_an_everdrive_save_never_takes_a_header(tmp_path: Path) -> None:
    # Arrange
    source = _game_with_a_file(tmp_path)

    # Act
    result = runner.invoke(
        app, ["convert", str(source), "-o", str(tmp_path / "bram.srm"), "--header"]
    )

    # Assert
    assert result.exit_code == 1
    assert "an .srm save is headerless" in result.stdout


def test_a_sharp_mz_disk_is_refused_by_name(tmp_path: Path) -> None:
    # Arrange
    source = tmp_path / "mz.qd"
    source.write_bytes(b"-QD format-" + b"\xff" * 5 + bytes(81920))

    # Act
    result = runner.invoke(app, ["info", str(source)])

    # Assert
    assert result.exit_code == 1
    assert "Sharp MZ Quick Disk image in QDF form, not a Famicom" in result.stdout


def test_dump_closes_the_drive_when_it_finishes(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach(monkeypatch, single_side)

    # Act
    runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.fds")])

    # Assert
    assert drive.closed


def test_dump_closes_the_drive_when_the_link_is_lost(
    image: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach(monkeypatch, image, plan=FaultPlan(link_lost_after=1))

    # Act
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.fds")])

    # Assert
    assert result.exit_code == 1
    assert drive.closed


def test_write_closes_the_drive(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach(monkeypatch, single_side)

    # Act
    runner.invoke(app, ["write", str(single_side), "--yes", "--backup", str(tmp_path / "b.fds")])

    # Assert
    assert drive.closed


def test_dump_keeps_the_drives_pulse_classes(
    single_side: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    attach(monkeypatch, single_side)

    # Act
    result = runner.invoke(
        app,
        ["dump", "-o", str(tmp_path / "dump.fds"), "--raw", str(tmp_path / "raw")],
    )

    # Assert
    assert "packed pulse classes" in result.stdout
    assert list((tmp_path / "raw").glob("*.raw03"))


def test_a_dump_names_a_gap_the_ram_adapter_would_skip(
    single_side: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    attach(monkeypatch, single_side, plan=FaultPlan(short_gap_before=1))

    # Act
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.fds")])

    # Assert
    assert "side 0: [FDS017] gap before this block is shorter" in result.stdout
    assert "(block 1, " in result.stdout


def test_a_dump_that_fails_still_keeps_the_captures_it_took(
    image: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    attach(monkeypatch, image, plan=FaultPlan(link_lost_after=1))

    # Act
    result = runner.invoke(
        app,
        ["dump", "-o", str(tmp_path / "dump.fds"), "--raw", str(tmp_path / "raw")],
    )

    # Assert
    assert result.exit_code == 1
    assert "the device stopped answering" in result.stdout
    assert list((tmp_path / "raw").glob("side0.read01.raw03"))
    assert not (tmp_path / "dump.fds").exists()


def test_dump_keeps_the_fdsstick_captures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    class CapturingStick(FdsStick):
        def __init__(self, disk: Disk) -> None:
            self._drive = SimulatedDrive(disk)
            self._captures = [Capture(side=0, read=1, data=b"\\x55" * 8)]
            self._resyncs = []
            self._pulse = []

        def status(self):  # noqa: ANN202
            return self._drive.status()

        def read_side(self, side: int):  # noqa: ANN202
            return self._drive.read_side(side)

    disk, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True))

    def open_capturing() -> CapturingStick:
        return CapturingStick(disk)

    monkeypatch.setattr(hardware_cmds, "open_fdsstick", open_capturing)

    # Act
    result = runner.invoke(
        app,
        ["dump", "-o", str(tmp_path / "dump.fds"), "--raw", str(tmp_path / "raw")],
    )

    # Assert
    assert (tmp_path / "raw" / "side0.read01.raw03").read_bytes() == b"\\x55" * 8
    assert load_bundle(tmp_path / "raw").image == "dump.fds"
    assert "packed pulse classes" in result.stdout


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


def test_web_starts_the_application(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    server = FakeUvicorn()
    monkeypatch.setitem(sys.modules, "uvicorn", server)

    # Act
    result = runner.invoke(app, ["web", "--port", "9123", "--no-open"])

    # Assert
    assert result.exit_code == 0
    assert server.started == [("127.0.0.1", 9123)]
    assert isinstance(server.apps[0], FastAPI)


def test_web_starts_hidapi_on_the_main_thread_before_it_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    order: list[str] = []

    class PrimedHid(FakeHid):
        def enumerate(self, vendor_id: int, product_id: int) -> list[dict[str, object]]:
            order.append("prime")
            return super().enumerate(vendor_id, product_id)

    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn(order))
    monkeypatch.setitem(sys.modules, "hid", PrimedHid([]))

    # Act
    result = runner.invoke(app, ["web", "--no-open"])

    # Assert
    assert result.exit_code == 0
    assert order == ["prime", "run"]


def test_web_verbose_prints_every_job_step(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn())
    package = logging.getLogger("fdstoolkit")
    before = (package.level, list(package.handlers))

    # Act
    result = runner.invoke(app, ["web", "--verbose", "--no-open"])

    # Assert
    level, handlers = package.level, list(package.handlers)
    package.setLevel(before[0])
    package.handlers = before[1]
    assert result.exit_code == 0
    assert level == logging.DEBUG
    assert len(handlers) == len(before[1]) + 1


def test_web_says_which_extra_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "uvicorn", None)

    # Act
    result = runner.invoke(app, ["web"])

    # Assert
    assert result.exit_code == 1
    assert "brew install" in result.stdout


def test_the_web_server_loader_returns_a_runner_and_a_factory() -> None:
    # Arrange
    loader = hardware_cmds.web_server

    # Act
    run, build = loader()

    # Assert
    assert callable(run)
    assert callable(build)


def test_dump_says_when_the_usb_link_skipped_packets(
    image: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    disk, _, _, _ = common.decode_image(image)
    packed = encode_raw03(disk, side=0)
    stick = FdsStick(HidApiTransport(FakeFdsStick(side=packed, drop_after=3)))
    monkeypatch.setattr(hardware_cmds, "open_fdsstick", lambda: stick)

    # Act
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "d.fds")])

    # Assert
    assert "the USB link skipped 1 packet(s) of pulse data" in result.stdout


def test_a_drive_that_returned_no_capture_says_so(tmp_path: Path) -> None:
    # Arrange
    drive = FdsStick(HidApiTransport(FakeFdsStick()))

    # Act
    hardware_cmds.keep_captures(drive, tmp_path, image="d.fds")

    # Assert
    assert not list(tmp_path.iterdir())


def test_dump_asks_the_operator_to_turn_the_disk_over(
    image: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
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

        @property
        def resyncs(self):  # noqa: ANN202
            return self._inner.resyncs

        @property
        def pulse_findings(self):  # noqa: ANN202
            return self._inner.pulse_findings

        def close(self) -> None:
            self._inner.close()

    disk, _, _, _ = common.decode_image(image)
    drive = OneFace(disk)

    def open_one_face(*args: object, **kwargs: object) -> OneFace:
        del args, kwargs
        return drive

    def flipped(message: str, *, err: bool) -> bool:
        del message, err
        drive.facing = 1
        return True

    monkeypatch.setattr(hardware_cmds, "open_fdsstick", open_one_face)
    monkeypatch.setattr(typer, "confirm", flipped)

    # Act
    result = runner.invoke(
        app,
        ["dump", "-o", str(tmp_path / "d.fds"), "--sides", "2"],
    )

    # Assert
    assert result.exit_code == 0


def test_surface_says_why_it_stopped_and_that_the_finish_was_skipped(
    single_side: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attach(monkeypatch, single_side, plan=FaultPlan(writes_do_not_stick=True))

    # Act
    result = runner.invoke(app, ["surface", "--yes", "--finish", "blank"])

    # Assert
    assert result.exit_code == 1
    assert f"stopped early: {StopReason.REFUSED.value}" in result.stdout
    assert "reads back exactly as it was before the write" in result.stdout
    assert "the finish was skipped because the test stopped early" in result.stdout


def test_surface_names_every_class_of_failing_block(capsys: pytest.CaptureFixture[str]) -> None:
    # Arrange
    report = SurfaceReport(
        passes=(
            PatternPass(
                SurfacePattern.SHORT,
                verified=False,
                mismatched_blocks=((0, 4), (0, 9)),
                grade=Grade.FAILED,
                short=30,
                long=1,
                compared=900,
            ),
            PatternPass(
                SurfacePattern.MEDIUM,
                verified=False,
                mismatched_blocks=((0, 4),),
                grade=Grade.FAILED,
                short=12,
                long=0,
                compared=400,
            ),
            PatternPass(
                SurfacePattern.LONG, verified=True, mismatched_blocks=(), grade=Grade.CLEAN
            ),
        ),
        coverage=0.98,
        data_bytes=53854,
        finish=Finish.ERASE,
        finish_verified=False,
        finish_ran=True,
        finish_problem="side 0 reads back exactly what was just written to side 1",
        blocks_per_side=14,
    )
    hardware_cmds.report_surface(report)

    # Act
    result = capsys.readouterr()

    # Assert
    assert "failed on more than one pattern" in result.out
    assert "marginal rather than dead" in result.out
    assert "rewriting refreshed them" in result.out
    assert "erased, with nothing the adapter can read" in result.out
    assert "which did not verify" in result.out
    assert "  side 0 reads back exactly what was just written to side 1" in result.out
    assert "side 0 pass 1 pattern short pulses: did not hold" in result.out
    assert "98.0% of the most any measured factory side carries" in result.out
    assert "42 read short and 1 read long" in result.out
    assert "the drive running fast" in result.out
    assert "the failures are spread across the side" in result.out
    assert "clean the disk surface gently" in result.out
    assert not report.passed


def test_dump_can_be_told_the_disk_is_already_turned_over(
    image: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
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

        @property
        def resyncs(self):  # noqa: ANN202
            return self._inner.resyncs

        @property
        def pulse_findings(self):  # noqa: ANN202
            return self._inner.pulse_findings

        def close(self) -> None:
            self._inner.close()

    disk, _, _, _ = common.decode_image(image)

    def open_one_face(*args: object, **kwargs: object) -> OneFace:
        del args, kwargs
        return OneFace(disk)

    monkeypatch.setattr(hardware_cmds, "open_fdsstick", open_one_face)

    # Act
    result = runner.invoke(
        app,
        ["dump", "-o", str(tmp_path / "d.fds"), "--sides", "2", "--yes"],
    )

    # Assert
    assert result.exit_code == 0
    assert "turn the disk over" in result.stderr


def test_web_opens_a_browser_unless_told_not_to(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    opened: list[str] = []

    def remember(address: str) -> bool:
        opened.append(address)
        return True

    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn())
    monkeypatch.setattr(webbrowser, "open", remember)

    # Act
    result = runner.invoke(app, ["web", "--port", "9124"])

    # Assert
    assert result.exit_code == 0
    assert opened == ["http://127.0.0.1:9124"]


def test_a_loopback_bind_says_nothing_leaves_this_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn())

    # Act
    result = runner.invoke(app, ["web", "--host", "127.0.0.1", "--no-open"])

    # Assert
    assert "nothing leaves this machine" in result.stdout


def test_a_published_bind_warns_instead_of_claiming_privacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn())

    # Act
    result = runner.invoke(app, ["web", "--host", PUBLISHED_HOST, "--no-open"])

    # Assert
    assert "nothing leaves this machine" not in result.stdout
    assert "there is no password" in result.stdout


def test_status_reports_a_ready_stick_and_what_it_cannot_say(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "hid", FakeHid([stick()]))

    # Act
    result = runner.invoke(app, ["status"])

    # Assert
    assert result.exit_code == 0
    assert "1 device(s) connected" in result.stdout
    assert "reports nothing about the disk itself" in result.stdout


def test_status_fails_and_marks_a_missing_stick(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "hid", FakeHid([]))

    # Act
    result = runner.invoke(app, ["status"])

    # Assert
    assert result.exit_code == 1
    assert "none connected at 16D0:0AAA" in result.stdout
    assert "[warning]" in result.stdout


def test_status_can_print_json(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "hid", FakeHid([]))

    # Act
    result = runner.invoke(app, ["status", "--json"])

    # Assert
    payload = json.loads(result.stdout)
    assert result.exit_code == 1
    assert payload["ready"] is False
    assert [check["name"] for check in payload["checks"]] == ["hardware support", "fdsstick"]


def test_dump_recovers_a_failed_block_from_the_reads_it_kept(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attach(monkeypatch, single_side, plan=FaultPlan(bad_crc_blocks=frozenset({1})))

    # Act
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.fds"), "--retries", "2"])

    # Assert
    assert "side 0 block 1: recovered by a pulse vote across 3 reads" in result.stdout
    assert "grade marginal" in result.stdout


def written_side_captures(tmp_path: Path) -> tuple[Path, Path]:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "fdsstick"
    image = tmp_path / "calibration.fds"
    image.write_bytes(fds.encode(calibration_disk(1), headered=False)[0])
    captures = tmp_path / "caps"
    capture = Capture(side=0, read=1, data=(fixture / "calibration-side.raw03").read_bytes())
    write_bundle(captures, [capture], image=image.name, created="2026-11-13T00:00:00Z")
    return image, captures


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


def test_build_names_the_field_a_toolkit_manifest_leaves_out(tmp_path: Path) -> None:
    # Arrange
    manifest = tmp_path / "disk.json"
    manifest.write_text(json.dumps({"game_name": "ABC", "sides": [{"files": [{"name": "X"}]}]}))
    arguments = ["build", str(manifest), "-o", str(tmp_path / "out.fds")]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 1
    assert "side 1 file 1 has no path" in result.output


def test_save_blank_names_the_field_a_recipe_leaves_out(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    recipes = tmp_path / "recipes.json"
    recipes.write_text(json.dumps({"version": 1, "recipes": [{"source": "a dump", "position": 0}]}))
    arguments = ["save", "blank", str(single_side), "--recipes", str(recipes)]
    arguments += ["-o", str(tmp_path / "out.fds")]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 1
    assert "recipe 1 has no game_name" in result.output


def test_set_refuses_a_date_the_disk_cannot_hold(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "dated.fds"
    arguments = ["set", str(single_side), "-o", str(out), "--set", "manufacturing_date=2030-01-01"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 1
    assert "outside 1925 to 2024" in result.output
    assert not out.exists()
