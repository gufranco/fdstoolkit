from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from device import FakeFdsStick
from drive_double import FaultPlan, SimulatedDrive
from main_kit import STALL_CEILING, SilentStick, attach, detach, runner

from fdstoolkit.cli import common, hardware_cmds
from fdstoolkit.cli.main import app
from fdstoolkit.codecs.raw import encode_raw03
from fdstoolkit.core.disk import SIDE_SIZE
from fdstoolkit.hardware.fdsstick import FdsStick, HidApiTransport
from fdstoolkit.hardware.ports import BlockRead

if TYPE_CHECKING:
    import pytest


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


def test_a_prompt_answered_by_yes_is_still_shown(capsys: pytest.CaptureFixture[str]) -> None:
    # Arrange
    ask = hardware_cmds.prompter(yes=True)

    # Act
    answered = ask("turn the disk over")

    # Assert
    assert answered
    assert "turn the disk over" in capsys.readouterr().err


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
