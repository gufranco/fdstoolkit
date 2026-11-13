from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from drive_double import FaultPlan, SimulatedDrive
from typer.testing import CliRunner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds
from fdstoolkit.core.bitstream import LEAD_IN_BITS
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Disk
from fdstoolkit.drive.monitor import NOT_THIS_DRIVE
from fdstoolkit.edit.files import FileSpec, insert_file

if TYPE_CHECKING:
    import pytest

runner = CliRunner()
FILES = 3


def disk_with(files: int) -> Disk:
    disk, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True, game_name="CAL"))
    for number in range(files):
        disk = insert_file(
            disk,
            side=0,
            spec=FileSpec(
                name=f"FILE{number:04d}",
                address=0x6000,
                kind=FileKind.PROGRAM,
                data=hashlib.sha256(f"file {number}".encode()).digest() * 4,
            ),
        )
    return disk


def saved(disk: Disk, path: Path) -> Path:
    data, _ = fds.encode(disk, headered=False)
    path.write_bytes(data)
    return path


def attach(
    monkeypatch: pytest.MonkeyPatch, disk: Disk | None, plan: FaultPlan | None = None
) -> None:
    drive = SimulatedDrive(disk, plan=plan)
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: drive)


def test_a_drive_that_reads_the_reference_clean_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    disk = disk_with(FILES)
    attach(monkeypatch, disk)
    reference = saved(disk, tmp_path / "reference.fds")
    arguments = ["calibrate", "speed", "--reference", str(reference), "--passes", "2"]
    first = (
        f"  read 1: 8 of 8 blocks, 0 pulses short, 0 long, 0 invalid, lead-in {LEAD_IN_BITS} bits: "
        "reads clean"
    )

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0, result.output
    assert NOT_THIS_DRIVE in result.output
    assert first in result.output
    assert "  read 2:" in result.output
    assert "the same as the last read" in result.output
    assert result.output.rstrip().splitlines()[-1].startswith("reads clean")


def test_a_disk_that_differs_from_the_reference_fails_and_names_the_blocks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    attach(monkeypatch, disk_with(FILES - 1))
    reference = saved(disk_with(FILES), tmp_path / "reference.fds")

    # Act
    result = runner.invoke(
        app, ["calibrate", "head", "--reference", str(reference), "--passes", "1"]
    )

    # Assert
    assert result.exit_code == 1
    assert "not read" in result.output


def test_without_a_reference_the_checksums_decide(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    attach(monkeypatch, disk_with(FILES))

    # Act
    result = runner.invoke(app, ["calibrate", "head", "--passes", "1"])

    # Assert
    assert result.exit_code == 0, result.output
    assert "pulses short" not in result.output
    assert "reads clean" in result.output


def test_a_calibration_prints_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Arrange
    disk = disk_with(FILES)
    attach(monkeypatch, disk)
    reference = saved(disk, tmp_path / "reference.fds")
    result = runner.invoke(
        app, ["calibrate", "speed", "--reference", str(reference), "--passes", "1", "--json"]
    )

    # Act
    payload = json.loads(result.stdout)

    # Assert
    assert payload["mode"] == "speed"
    assert "judge the drive only with a disk it did not write" in result.stderr
    assert payload["clean"] is True
    assert payload["reads"][0]["verdict"] == "reads clean"
    assert payload["spread"] == {"reads clean": 1}


def test_a_reference_side_the_image_lacks_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    attach(monkeypatch, disk_with(FILES))
    reference = saved(disk_with(FILES), tmp_path / "reference.fds")

    # Act
    result = runner.invoke(
        app, ["calibrate", "speed", "--reference", str(reference), "--side", "1"]
    )

    # Assert
    assert result.exit_code == 1
    assert "has 1 side(s), so it has no side 1" in result.output


def test_a_drive_that_stops_answering_ends_the_calibration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    attach(monkeypatch, None)

    # Act
    result = runner.invoke(app, ["calibrate", "speed", "--passes", "1"])

    # Assert
    assert result.exit_code == 1
    assert "no disk in the drive" in result.output


def test_a_mode_it_does_not_know_is_refused() -> None:
    # Arrange
    arguments = ["calibrate", "belt"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 2


def test_a_bracketed_calibration_asks_before_every_read_after_the_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    disk = disk_with(FILES)
    attach(monkeypatch, disk)
    reference = saved(disk, tmp_path / "reference.fds")

    # Act
    result = runner.invoke(
        app,
        ["calibrate", "head", "--reference", str(reference), "--passes", "3", "--bracket"],
        input="y\ny\n",
    )

    # Assert
    assert result.output.count("turn the adjustment one small step") == 2
    assert "it still reads: keep turning the same way until it stops" in result.output


def attach_counting(monkeypatch: pytest.MonkeyPatch, disk: Disk | None) -> SimulatedDrive:
    drive = SimulatedDrive(disk, sends_counts=True)
    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", lambda: drive)
    return drive


def test_a_calibration_on_a_stick_that_sends_classes_shows_no_timing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    attach(monkeypatch, disk_with(FILES))
    result = runner.invoke(app, ["calibrate", "speed", "--passes", "1", "--json"])

    # Act
    payload = json.loads(result.stdout)

    # Assert
    assert "timing" not in result.stderr
    assert payload["timing"] == []
    assert result.exit_code == 0


def test_a_calibration_on_a_stick_that_sends_counts_shows_the_timing_of_each_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    attach_counting(monkeypatch, disk_with(FILES))
    result = runner.invoke(app, ["calibrate", "speed", "--passes", "2", "--json"])

    # Act
    payload = json.loads(result.stdout)

    # Assert
    assert result.stderr.count("timing: short") == 2
    assert len(payload["timing"]) == 2
    assert payload["clean"] is True
