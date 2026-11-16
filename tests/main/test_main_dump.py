from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from drive_double import FaultPlan, SimulatedDrive
from main_kit import attach, runner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli import common, hardware_cmds
from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds, qd
from fdstoolkit.core.blocks import CrcStatus
from fdstoolkit.core.disk import SIDE_SIZE, Disk
from fdstoolkit.drive.captures import Capture, load_bundle
from fdstoolkit.drive.pulse import PulseFinding
from fdstoolkit.hardware.fdsstick import FdsStick
from fdstoolkit.hardware.ports import BlockRead, DriveStatus

if TYPE_CHECKING:
    import pytest


class CapturingStick(FdsStick):
    def __init__(self, disk: Disk) -> None:
        self._drive = SimulatedDrive(disk)
        self._captures = [Capture(side=0, read=1, data=b"\\x55" * 8)]
        self._resyncs = []
        self._pulse = []

    def status(self) -> DriveStatus:
        return self._drive.status()

    def read_side(self, side: int) -> Iterator[BlockRead]:
        return self._drive.read_side(side)


class OneFace:
    selects_sides = False

    def __init__(self, disk: Disk) -> None:
        self._inner = SimulatedDrive(disk)
        self.facing = 0

    def status(self) -> DriveStatus:
        return self._inner.status()

    def read_side(self, side: int) -> Iterator[BlockRead]:
        del side
        return self._inner.read_side(self.facing)

    def turn_over(self, message: str, *, err: bool) -> bool:
        del message, err
        self.facing = 1
        return True

    @property
    def captures(self) -> tuple[Capture, ...]:
        return self._inner.captures

    @property
    def resyncs(self) -> tuple[tuple[int, int], ...]:
        return self._inner.resyncs

    @property
    def pulse_findings(self) -> tuple[PulseFinding, ...]:
        return self._inner.pulse_findings

    def close(self) -> None:
        self._inner.close()


class TurnedOneFace(OneFace):
    def read_side(self, side: int) -> Iterator[BlockRead]:
        self.facing = side
        return super().read_side(side)


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


def test_dump_reports_a_missing_fdsstick(tmp_path: Path) -> None:
    # Arrange
    arguments = ["dump", "-o", str(tmp_path / "dump.fds")]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 1
    assert "FDSStick" in result.stdout or "hidapi" in result.stdout


def test_dump_reports_unstable_blocks(
    image: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    attach(monkeypatch, image)

    # Act
    result = runner.invoke(app, ["dump", "-o", str(tmp_path / "d.fds"), "--passes", "2"])

    # Assert
    assert result.exit_code == 0


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


def test_dump_closes_the_drive_when_it_finishes(
    single_side: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    drive = attach(monkeypatch, single_side)

    # Act
    runner.invoke(app, ["dump", "-o", str(tmp_path / "dump.fds")])

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


def test_dump_keeps_the_fdsstick_captures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    disk, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True))
    monkeypatch.setattr(hardware_cmds, "open_fdsstick", lambda: CapturingStick(disk))

    # Act
    result = runner.invoke(
        app,
        ["dump", "-o", str(tmp_path / "dump.fds"), "--raw", str(tmp_path / "raw")],
    )

    # Assert
    assert (tmp_path / "raw" / "side0.read01.raw03").read_bytes() == b"\\x55" * 8
    assert load_bundle(tmp_path / "raw").image == "dump.fds"
    assert "packed pulse classes" in result.stdout


def test_dump_asks_the_operator_to_turn_the_disk_over(
    image: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    disk, _, _, _ = common.decode_image(image)
    drive = OneFace(disk)
    monkeypatch.setattr(hardware_cmds, "open_fdsstick", lambda: drive)
    monkeypatch.setattr(typer, "confirm", drive.turn_over)

    # Act
    result = runner.invoke(
        app,
        ["dump", "-o", str(tmp_path / "d.fds"), "--sides", "2"],
    )

    # Assert
    assert result.exit_code == 0


def test_dump_can_be_told_the_disk_is_already_turned_over(
    image: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    disk, _, _, _ = common.decode_image(image)
    monkeypatch.setattr(hardware_cmds, "open_fdsstick", lambda: TurnedOneFace(disk))

    # Act
    result = runner.invoke(
        app,
        ["dump", "-o", str(tmp_path / "d.fds"), "--sides", "2", "--yes"],
    )

    # Assert
    assert result.exit_code == 0
    assert "turn the disk over" in result.stderr
