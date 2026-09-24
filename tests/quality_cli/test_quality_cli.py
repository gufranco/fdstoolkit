from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side

runner = CliRunner()


def _payload(tail: bytes = bytes(41)) -> bytes:
    return bytes([BlockKind.DISK_INFO]) + b"*NINTENDO-HVC*" + tail


def _write(path: Path, *, tail: bytes = bytes(41)) -> Path:
    disk = Disk(
        sides=(
            Side(
                blocks=(Block(kind=BlockKind.DISK_INFO, payload=_payload(tail)),),
                tail=b"",
                capacity=65500,
            ),
        )
    )
    data, _ = fds.encode(disk, headered=False)
    path.write_bytes(data)
    return path


def test_identical_dumps_report_full_stability(tmp_path: Path) -> None:
    first = _write(tmp_path / "a.fds")
    second = _write(tmp_path / "b.fds")

    result = runner.invoke(app, ["reads", str(first), str(second)])

    assert result.exit_code == 0
    assert "stability" in result.stdout


def test_differing_dumps_report_the_unstable_block(tmp_path: Path) -> None:
    first = _write(tmp_path / "a.fds")
    second = _write(tmp_path / "b.fds", tail=bytes([0x0F]) + bytes(40))

    result = runner.invoke(app, ["reads", str(first), str(second)])

    assert result.exit_code == 1
    assert "block" in result.stdout


def test_reads_can_print_json(tmp_path: Path) -> None:
    first = _write(tmp_path / "a.fds")
    second = _write(tmp_path / "b.fds")

    result = runner.invoke(app, ["reads", str(first), str(second), "--json"])

    payload = json.loads(result.stdout)
    assert payload["passes"] == 2
    assert payload["stability"] == 1.0
    assert payload["decay"] == "none"


def test_a_single_dump_is_refused(tmp_path: Path) -> None:
    result = runner.invoke(app, ["reads", str(_write(tmp_path / "a.fds"))])

    assert result.exit_code == 1
    assert "at least two" in result.stdout


def test_an_image_can_be_graded(tmp_path: Path) -> None:
    result = runner.invoke(app, ["grade", str(_write(tmp_path / "a.fds"))])

    assert result.exit_code == 0
    assert "confidence" in result.stdout


def test_grading_can_print_json(tmp_path: Path) -> None:
    result = runner.invoke(app, ["grade", str(_write(tmp_path / "a.fds")), "--json"])

    payload = json.loads(result.stdout)
    assert "grade" in payload
    assert "reasons" in payload


def test_grading_can_read_repeated_dumps(tmp_path: Path) -> None:
    first = _write(tmp_path / "a.fds")
    second = _write(tmp_path / "b.fds")

    result = runner.invoke(app, ["grade", str(first), "--read", str(second)])

    assert result.exit_code == 0
    assert "read stability" in result.stdout


def test_grading_can_show_the_per_block_confidence(tmp_path: Path) -> None:
    result = runner.invoke(app, ["grade", str(_write(tmp_path / "a.fds")), "--map"])

    assert "disk_info" in result.stdout


def test_a_drive_reading_the_reference_back_is_good(tmp_path: Path) -> None:
    reference = _write(tmp_path / "ref.fds")
    read = _write(tmp_path / "r1.fds")

    result = runner.invoke(app, ["health", str(reference), "--read", str(read)])

    assert result.exit_code == 0
    assert "good" in result.stdout


def test_a_drive_that_misreads_is_reported(tmp_path: Path) -> None:
    reference = _write(tmp_path / "ref.fds")
    read = _write(tmp_path / "r1.fds", tail=bytes([0xAA]) + bytes(40))

    result = runner.invoke(app, ["health", str(reference), "--read", str(read)])

    assert result.exit_code == 1
    assert "faulty" in result.stdout


def test_health_needs_a_read(tmp_path: Path) -> None:
    result = runner.invoke(app, ["health", str(_write(tmp_path / "ref.fds"))])

    assert result.exit_code == 1
    assert "at least one read" in result.stdout


def test_a_sound_image_passes_the_integrity_check(tmp_path: Path) -> None:
    result = runner.invoke(app, ["integrity", str(_write(tmp_path / "a.fds"))])

    assert result.exit_code == 0
    assert "sound" in result.stdout


def test_integrity_can_print_json(tmp_path: Path) -> None:
    result = runner.invoke(app, ["integrity", str(_write(tmp_path / "a.fds")), "--json"])

    assert json.loads(result.stdout)["sound"] is True
