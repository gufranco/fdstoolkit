from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from drive_double import FacingDrive
from typer.testing import CliRunner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.calibration import TRUSTED_DRIVE, calibration_disk, calibration_image
from fdstoolkit.cli import hardware_cmds
from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

runner = CliRunner()


def blank_two_sides() -> FacingDrive:
    disk, _ = fds.decode(blank_image(sides=2, headered=False, formatted=True, game_name="OLD"))
    return FacingDrive(disk)


def turning(drive: FacingDrive) -> Callable[..., Callable[[str], bool]]:
    def answer(message: str) -> bool:
        if "turn the disk over" in message:
            drive.turn(message)
        return True

    def build(*, yes: bool) -> Callable[[str], bool]:
        del yes
        return answer

    return build


def attach(monkeypatch: pytest.MonkeyPatch) -> FacingDrive:
    drive = blank_two_sides()
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: drive)
    monkeypatch.setattr(hardware_cmds, "prompter", turning(drive))
    return drive


def test_blank_writes_the_calibration_image(tmp_path: Path) -> None:
    output = tmp_path / "calibration.fds"

    result = runner.invoke(app, ["blank", "--calibration", "-o", str(output)])

    assert result.exit_code == 0, result.output
    assert output.read_bytes() == calibration_image(headered=False)
    assert "write it only on a drive you trust" in result.output


def test_blank_can_add_a_header_to_the_calibration_image(tmp_path: Path) -> None:
    output = tmp_path / "calibration.fds"

    result = runner.invoke(app, ["blank", "--calibration", "--header", "-o", str(output)])

    assert result.exit_code == 0, result.output
    assert output.read_bytes() == calibration_image(headered=True)


def test_blank_refuses_options_the_calibration_image_decides(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["blank", "--calibration", "--game-name", "ABC", "-o", str(tmp_path / "x.fds")]
    )

    assert result.exit_code == 1
    assert "decides its own sides, format and game name" in result.output


def test_writing_the_calibration_disk_needs_the_trusted_drive_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drive = attach(monkeypatch)

    result = runner.invoke(app, ["write", "--calibration"])

    assert result.exit_code == 1
    assert "trusted drive confirmation" in result.output
    assert "Pass --trusted-drive" in result.output
    assert all(line in result.output for line in TRUSTED_DRIVE)
    assert drive.write_count == 0


def test_the_calibration_disk_is_written_and_read_back_on_both_sides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drive = attach(monkeypatch)

    result = runner.invoke(app, ["write", "--calibration", "--trusted-drive"])

    assert result.exit_code == 0, result.output
    assert "verified True" in result.output
    assert drive.turns == 1
    assert TRUSTED_DRIVE[-1] in result.output
    written = drive.disk
    assert written is not None
    assert [[b.payload for b in side.blocks] for side in written.sides] == [
        [b.payload for b in side.blocks] for side in calibration_disk().sides
    ]


def test_write_takes_an_image_or_the_calibration_disk_never_both(tmp_path: Path) -> None:
    image = tmp_path / "game.fds"
    image.write_bytes(blank_image(sides=1, headered=False, formatted=True))

    both = runner.invoke(app, ["write", str(image), "--calibration", "--trusted-drive"])
    neither = runner.invoke(app, ["write"])

    assert both.exit_code == neither.exit_code == 1
    assert "an image or the calibration disk" in both.output
    assert "an image or the calibration disk" in neither.output


def test_trusted_drive_only_means_something_with_the_calibration_disk(tmp_path: Path) -> None:
    image = tmp_path / "game.fds"
    image.write_bytes(blank_image(sides=1, headered=False, formatted=True))

    result = runner.invoke(app, ["write", str(image), "--trusted-drive"])

    assert result.exit_code == 1
    assert "only applies to the calibration disk" in result.output
