from __future__ import annotations

import json
from pathlib import Path

from main_kit import GAME, OTHER_GAME, THIRD_GAME, runner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app
from fdstoolkit.codecs.qd import encode as encode_qd
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import SIDE_SIZE, Disk, Side


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


def test_patch_applies_an_ips(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    patch = tmp_path / "rename.ips"
    patch.write_bytes(
        b"PATCH"
        + (0x10).to_bytes(3, "big")
        + (3).to_bytes(2, "big")
        + OTHER_GAME.encode("ascii")
        + b"EOF"
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
        == OTHER_GAME
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


def test_build_writes_a_disk_from_a_manifest(tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "main.prg"
    payload.write_bytes(bytes([0x11]) * 32)
    manifest = tmp_path / "disk.json"
    manifest.write_text(
        json.dumps(
            {
                "game_name": GAME,
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
    manifest.write_text(json.dumps({"game_name": GAME, "sides": []}), encoding="utf-8")

    # Act
    result = runner.invoke(app, ["build", str(manifest), "-o", str(tmp_path / "out.fds")])

    # Assert
    assert result.exit_code == 1
    assert "at least one side" in result.stdout


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


def test_build_names_the_field_a_toolkit_manifest_leaves_out(tmp_path: Path) -> None:
    # Arrange
    manifest = tmp_path / "disk.json"
    manifest.write_text(
        json.dumps({"game_name": THIRD_GAME, "sides": [{"files": [{"name": "X"}]}]})
    )
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
