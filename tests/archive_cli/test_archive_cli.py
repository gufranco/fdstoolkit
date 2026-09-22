from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side

runner = CliRunner()


def _write(path: Path, *, serial: int = 0x1234) -> Path:
    payload = bytearray(56)
    payload[0x00] = BlockKind.DISK_INFO
    payload[0x01:0x0F] = b"*NINTENDO-HVC*"
    payload[0x10:0x13] = b"ABC"
    payload[0x31:0x33] = serial.to_bytes(2, "little")
    disk = Disk(
        sides=(
            Side(
                blocks=(Block(kind=BlockKind.DISK_INFO, payload=bytes(payload)),),
                tail=b"",
                capacity=65500,
            ),
        )
    )
    data, _ = fds.encode(disk, headered=False)
    path.write_bytes(data)
    return path


def test_a_dump_is_recorded_and_listed(tmp_path: Path) -> None:
    db = tmp_path / "archive.db"
    image = _write(tmp_path / "a.fds")

    added = runner.invoke(
        app, ["archive-add", str(image), "--db", str(db), "--taken", "2026-09-22"]
    )
    assert added.exit_code == 0
    assert "recorded" in added.stdout

    listed = runner.invoke(app, ["archive-trend", "--db", str(db)])
    assert listed.exit_code == 0
    assert "not enough history" in listed.stdout


def test_two_dumps_a_year_apart_show_a_direction(tmp_path: Path) -> None:
    db = tmp_path / "archive.db"
    image = _write(tmp_path / "a.fds")

    runner.invoke(app, ["archive-add", str(image), "--db", str(db), "--taken", "2024-01-01"])
    runner.invoke(
        app,
        ["archive-add", str(image), "--db", str(db), "--taken", "2026-01-01", "--bad-blocks", "20"],
    )

    result = runner.invoke(app, ["archive-trend", "--db", str(db)])

    assert "degrading" in result.stdout


def test_the_trend_can_print_json(tmp_path: Path) -> None:
    db = tmp_path / "archive.db"
    image = _write(tmp_path / "a.fds")
    runner.invoke(app, ["archive-add", str(image), "--db", str(db), "--taken", "2024-01-01"])
    runner.invoke(
        app,
        ["archive-add", str(image), "--db", str(db), "--taken", "2026-01-01", "--bad-blocks", "20"],
    )

    result = runner.invoke(app, ["archive-trend", "--db", str(db), "--json"])

    payload = json.loads(result.stdout)
    assert payload[0]["direction"] == "degrading"
    assert payload[0]["points"] == 2


def test_one_disk_can_be_named(tmp_path: Path) -> None:
    db = tmp_path / "archive.db"
    image = _write(tmp_path / "a.fds")
    added = runner.invoke(
        app, ["archive-add", str(image), "--db", str(db), "--taken", "2026-01-01"]
    )
    disk_id = added.stdout.split()[-1]

    result = runner.invoke(app, ["archive-trend", "--db", str(db), "--disk", disk_id])

    assert result.exit_code == 0


def test_an_unknown_disk_is_refused(tmp_path: Path) -> None:
    db = tmp_path / "archive.db"
    _write(tmp_path / "a.fds")
    runner.invoke(app, ["archive-add", str(tmp_path / "a.fds"), "--db", str(db)])

    result = runner.invoke(app, ["archive-trend", "--db", str(db), "--disk", "nobody"])

    assert result.exit_code == 1
    assert "no history" in result.stdout


def test_an_empty_archive_reports_nothing(tmp_path: Path) -> None:
    result = runner.invoke(app, ["archive-trend", "--db", str(tmp_path / "empty.db")])

    assert result.exit_code == 0
    assert "no disk" in result.stdout


def test_a_bad_date_is_refused(tmp_path: Path) -> None:
    db = tmp_path / "archive.db"
    image = _write(tmp_path / "a.fds")

    result = runner.invoke(app, ["archive-add", str(image), "--db", str(db), "--taken", "nope"])

    assert result.exit_code == 1
    assert "not a date" in result.stdout


def test_two_physical_copies_are_tracked_apart(tmp_path: Path) -> None:
    db = tmp_path / "archive.db"
    runner.invoke(app, ["archive-add", str(_write(tmp_path / "a.fds", serial=1)), "--db", str(db)])
    runner.invoke(app, ["archive-add", str(_write(tmp_path / "b.fds", serial=2)), "--db", str(db)])

    result = runner.invoke(app, ["archive-trend", "--db", str(db), "--json"])

    assert len(json.loads(result.stdout)) == 2
