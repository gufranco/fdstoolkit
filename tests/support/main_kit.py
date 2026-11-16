from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from drive_double import FacingDrive, FaultPlan, SimulatedDrive
from fakes import game_name, seeded
from typer.testing import CliRunner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.calibration import LARGEST_FACTORY_SIDE, calibration_disk
from fdstoolkit.cli import common
from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds
from fdstoolkit.codecs.qd import encode as encode_qd
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.drive.captures import Capture, write_bundle
from fdstoolkit.edit.files import FileSpec, insert_file
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError

if TYPE_CHECKING:
    import pytest

runner = CliRunner()


FAKE = seeded("main")
GAME = game_name(FAKE)
OTHER_GAME = game_name(FAKE)
THIRD_GAME = game_name(FAKE)
STALL_CEILING = 0.05


PUBLISHED_HOST = "0.0.0.0"  # noqa: S104


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


def detach(monkeypatch: pytest.MonkeyPatch, message: str = "no FDSStick is attached") -> None:
    def opener() -> SimulatedDrive:
        raise HardwareFaultError(message, kind=FaultKind.LINK)

    monkeypatch.setattr("fdstoolkit.cli.hardware_cmds.open_fdsstick", opener)


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


def game_with_a_file(tmp_path: Path, name: str = "Game") -> Path:
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


def written_side_captures(tmp_path: Path) -> tuple[Path, Path]:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "fdsstick"
    image = tmp_path / "calibration.fds"
    image.write_bytes(fds.encode(calibration_disk(1), headered=False)[0])
    captures = tmp_path / "caps"
    capture = Capture(side=0, read=1, data=(fixture / "calibration-side.raw03").read_bytes())
    write_bundle(captures, [capture], image=image.name, created="2026-11-13T00:00:00Z")
    return image, captures


def oversized_qd(size: int) -> bytes:
    info = bytearray(56)
    info[0] = 0x01
    info[1:15] = b"*NINTENDO-HVC*"
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
    return data
