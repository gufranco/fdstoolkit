from __future__ import annotations

import json
from pathlib import Path

from capture_fixture import CREATED, DAMAGED, IMAGE, captures_of, disk_with_a_file, image_of
from typer.testing import CliRunner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds
from fdstoolkit.core.disk import Disk
from fdstoolkit.drive.captures import write_bundle

runner = CliRunner()


def bundle_of(tmp_path: Path, offsets: tuple[int | None, ...]) -> tuple[Path, Disk]:
    disk = disk_with_a_file()
    directory = tmp_path / "captures"
    write_bundle(directory, captures_of(disk, offsets), image=IMAGE, created=CREATED)
    return directory, disk


def saved(disk: Disk, path: Path) -> Path:
    path.write_bytes(image_of(disk))
    return path


def test_consensus_rebuilds_a_disk_from_saved_captures(tmp_path: Path) -> None:
    bundle, disk = bundle_of(tmp_path, (10, 90, 170))
    output = tmp_path / "rebuilt.fds"

    result = runner.invoke(app, ["consensus", "--captures", str(bundle), "-o", str(output)])

    assert result.exit_code == 0, result.output
    assert "1 block(s) recovered by a pulse vote" in result.output
    rebuilt, _ = fds.decode(output.read_bytes())
    assert [b.payload for b in rebuilt.sides[0].blocks] == [b.payload for b in disk.sides[0].blocks]


def test_consensus_merges_saved_captures_with_image_dumps(tmp_path: Path) -> None:
    bundle, disk = bundle_of(tmp_path, (10, 90, 170))
    dump = saved(disk, tmp_path / "dump.fds")
    output = tmp_path / "merged.fds"

    result = runner.invoke(
        app, ["consensus", str(dump), "--captures", str(bundle), "-o", str(output)]
    )

    assert result.exit_code == 0, result.output
    assert output.is_file()


def test_consensus_of_dumps_and_captures_prints_only_json_on_stdout(tmp_path: Path) -> None:
    bundle, disk = bundle_of(tmp_path, (10, 90, 170))
    dump = saved(disk, tmp_path / "dump.fds")
    output = tmp_path / "merged.fds"

    result = runner.invoke(
        app, ["consensus", str(dump), "--captures", str(bundle), "-o", str(output), "--json"]
    )

    assert json.loads(result.stdout)["output"] == str(output)
    assert "recovered by a pulse vote" in result.stderr


def test_consensus_says_which_block_the_captures_could_not_fix(tmp_path: Path) -> None:
    bundle, _ = bundle_of(tmp_path, (10,))

    result = runner.invoke(
        app, ["consensus", "--captures", str(bundle), "-o", str(tmp_path / "out.fds")]
    )

    assert result.exit_code == 1
    assert f"block {DAMAGED}: never read clean" in result.output


def test_consensus_needs_something_to_merge(tmp_path: Path) -> None:
    result = runner.invoke(app, ["consensus", "-o", str(tmp_path / "out.fds")])

    assert result.exit_code == 1
    assert "needs dumps, saved captures, or both" in result.output


def test_consensus_refuses_a_bundle_that_does_not_load(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["consensus", "--captures", str(tmp_path), "-o", str(tmp_path / "out.fds")]
    )

    assert result.exit_code == 1
    assert "no manifest.json" in result.output


def test_reads_maps_the_weak_blocks_in_saved_captures(tmp_path: Path) -> None:
    bundle, _ = bundle_of(tmp_path, (None, 10, None))

    result = runner.invoke(app, ["reads", "--captures", str(bundle)])

    assert result.exit_code == 1
    assert f"side 0 block {DAMAGED} (file data)" in result.output


def test_reads_of_steady_captures_finds_no_weak_block(tmp_path: Path) -> None:
    bundle, _ = bundle_of(tmp_path, (None, None, None))

    result = runner.invoke(app, ["reads", "--captures", str(bundle), "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["weak"] == []


def test_reads_still_needs_two_dumps_without_captures(tmp_path: Path) -> None:
    dump = saved(disk_with_a_file(), tmp_path / "one.fds")

    result = runner.invoke(app, ["reads", str(dump)])

    assert result.exit_code == 1


def test_grade_counts_weak_blocks_from_saved_captures(tmp_path: Path) -> None:
    bundle, disk = bundle_of(tmp_path, (None, 10, None))
    image = saved(disk, tmp_path / "dump.fds")

    result = runner.invoke(app, ["grade", str(image), "--captures", str(bundle), "--json"])

    payload = json.loads(result.output)
    assert payload["grade"] == "marginal"
    assert {"metric": "weak blocks", "value": 1, "threshold": 0.0, "passed": False} in payload[
        "reasons"
    ]


def test_calibrate_reads_saved_captures_without_a_drive(tmp_path: Path) -> None:
    bundle, disk = bundle_of(tmp_path, (10, None))
    reference = saved(disk, tmp_path / "reference.fds")

    result = runner.invoke(
        app,
        ["calibrate", "head", "--reference", str(reference), "--captures", str(bundle)],
    )

    assert result.exit_code == 0, result.output
    assert "  read 1:" in result.output
    assert "  read 2:" in result.output
    assert "console error 27" in result.output


def test_calibrate_says_when_the_captures_hold_no_read_of_that_side(tmp_path: Path) -> None:
    bundle, _ = bundle_of(tmp_path, (None,))

    result = runner.invoke(app, ["calibrate", "speed", "--captures", str(bundle), "--side", "1"])

    assert result.exit_code == 1
    assert "holds no read of side 1" in result.output


def test_consensus_from_captures_reports_json(tmp_path: Path) -> None:
    bundle, _ = bundle_of(tmp_path, (10,))
    output = tmp_path / "out.fds"

    result = runner.invoke(
        app, ["consensus", "--captures", str(bundle), "-o", str(output), "--json"]
    )

    payload = json.loads(result.output)
    assert result.exit_code == 1
    assert payload["output"] == str(output)
    assert payload["unresolved"] == [[0, DAMAGED]]


def test_grade_refuses_captures_of_another_disk(tmp_path: Path) -> None:
    bundle, _ = bundle_of(tmp_path, (None, None, None))
    other, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True, game_name="OTH"))
    image = saved(other, tmp_path / "other.fds")

    result = runner.invoke(app, ["grade", str(image), "--captures", str(bundle)])

    assert result.exit_code == 1
    assert "the captures are of another disk" in result.stdout


def test_grade_cannot_compare_captures_with_an_image_that_holds_no_block(tmp_path: Path) -> None:
    bundle, _ = bundle_of(tmp_path, (None, None, None))
    empty = tmp_path / "empty.fds"
    empty.write_bytes(bytes(fds.SIDE_SIZE))

    result = runner.invoke(app, ["grade", str(empty), "--captures", str(bundle)])

    assert "the captures are of another disk" not in result.stdout
