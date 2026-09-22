from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from fdstoolkit.cli.main import app
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.flux.counts import write_counts
from fdstoolkit.flux.scp import write_scp
from fdstoolkit.flux.synth import synthesise

runner = CliRunner()


def _disk() -> Disk:
    payload = bytes([BlockKind.DISK_INFO]) + b"*NINTENDO-HVC*" + bytes(41)
    return Disk(
        sides=(
            Side(
                blocks=(Block(kind=BlockKind.DISK_INFO, payload=payload),),
                tail=b"",
                capacity=65500,
            ),
        )
    )


def _capture(tmp_path: Path, *, jitter: int = 0) -> Path:
    path = tmp_path / "capture.scp"
    path.write_bytes(write_scp(synthesise(_disk(), jitter_ns=jitter, seed=1)))
    return path


def test_measuring_a_clean_capture_succeeds(tmp_path: Path) -> None:
    result = runner.invoke(app, ["flux", str(_capture(tmp_path))])

    assert result.exit_code == 0
    assert "healthy" in result.stdout
    assert "bit cell" in result.stdout


def test_the_measurement_reports_the_bit_cell(tmp_path: Path) -> None:
    result = runner.invoke(app, ["flux", str(_capture(tmp_path)), "--json"])

    payload = json.loads(result.stdout)
    assert payload["format"] == "scp"
    assert 9_000 < payload["tracks"][0]["base_ns"] < 12_000
    assert payload["healthy"]


def test_a_degraded_capture_reports_a_failing_status(tmp_path: Path) -> None:
    result = runner.invoke(app, ["flux", str(_capture(tmp_path, jitter=2_800))])

    assert result.exit_code == 1
    assert "degraded" in result.stdout


def test_a_missing_capture_is_refused(tmp_path: Path) -> None:
    result = runner.invoke(app, ["flux", str(tmp_path / "nothing.scp")])

    assert result.exit_code == 1
    assert "file not found" in result.stdout


def test_an_unreadable_capture_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad.scp"
    path.write_bytes(b"SCP" + bytes(20))

    result = runner.invoke(app, ["flux", str(path)])

    assert result.exit_code == 1
    assert "too short" in result.stdout


def test_a_capture_decodes_back_into_an_image(tmp_path: Path) -> None:
    output = tmp_path / "out.fds"

    result = runner.invoke(app, ["flux-decode", str(_capture(tmp_path)), "-o", str(output)])

    assert result.exit_code == 0
    assert output.is_file()
    assert b"*NINTENDO-HVC*" in output.read_bytes()


def test_decoding_can_use_fixed_thresholds(tmp_path: Path) -> None:
    output = tmp_path / "out.fds"

    result = runner.invoke(
        app, ["flux-decode", str(_capture(tmp_path)), "-o", str(output), "--fixed"]
    )

    assert result.exit_code == 0


def test_decoding_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    output = tmp_path / "out.fds"
    output.write_bytes(b"")

    result = runner.invoke(app, ["flux-decode", str(_capture(tmp_path)), "-o", str(output)])

    assert result.exit_code == 1
    assert "--force" in result.stdout


def test_a_counts_capture_can_be_named_explicitly(tmp_path: Path) -> None:
    path = tmp_path / "capture.raw"
    path.write_bytes(write_counts(synthesise(_disk())))

    result = runner.invoke(app, ["flux", str(path), "--format", "counts", "--json"])

    assert json.loads(result.stdout)["format"] == "counts"
