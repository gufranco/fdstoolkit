from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app

runner = CliRunner()


def _save_disk(tmp_path: Path, fill: int, name: str) -> Path:
    content = bytearray(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    content[56:58] = bytes([0x02, 0x01])
    header = (
        bytes([0x03, 0x00, 0x00])
        + b"FC_SAVE "
        + (0x6000).to_bytes(2, "little")
        + (4).to_bytes(2, "little")
        + bytes([0x00])
    )
    content[58:74] = header
    content[74:79] = bytes([0x04]) + bytes([fill]) * 4
    path = tmp_path / name
    path.write_bytes(bytes(content))
    return path


def _recipes(tmp_path: Path) -> Path:
    path = tmp_path / "recipes.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "recipes": [
                    {
                        "game_name": "SMB",
                        "game_version": 0,
                        "side": 0,
                        "position": 0,
                        "fill": 0,
                        "source": "two dumps of one release differ only here",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def single_side(tmp_path: Path) -> Path:
    path = tmp_path / "one-side.fds"
    path.write_bytes(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    return path


def test_save_find_reports_no_candidate_for_identical_dumps(single_side: Path) -> None:
    result = runner.invoke(app, ["save", "find", str(single_side), str(single_side)])

    assert result.exit_code == 0
    assert "no save candidate" in result.stdout


def test_save_find_needs_two_dumps(single_side: Path) -> None:
    result = runner.invoke(app, ["save", "find", str(single_side)])

    assert result.exit_code == 1
    assert "two or more" in result.stdout


def test_save_extract_then_apply_round_trips(single_side: Path, tmp_path: Path) -> None:
    played = tmp_path / "played.fds"
    data = bytearray(single_side.read_bytes())
    data[70:78] = bytes([0x22]) * 8
    played.write_bytes(bytes(data))
    save = tmp_path / "save.ips"
    merged = tmp_path / "merged.fds"

    extracted = runner.invoke(
        app,
        ["save", "extract", str(single_side), "--played", str(played), "-o", str(save)],
    )
    applied = runner.invoke(
        app,
        ["save", "apply", str(single_side), "--save", str(save), "-o", str(merged)],
    )

    assert extracted.exit_code == 0
    assert applied.exit_code == 0
    assert merged.read_bytes() == played.read_bytes()


def test_save_apply_reports_a_missing_save(single_side: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "save",
            "apply",
            str(single_side),
            "--save",
            str(tmp_path / "nope.ips"),
            "-o",
            str(tmp_path / "out.fds"),
        ],
    )

    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_save_extract_reports_a_missing_played_image(single_side: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "save",
            "extract",
            str(single_side),
            "--played",
            str(tmp_path / "nope.fds"),
            "-o",
            str(tmp_path / "out.ips"),
        ],
    )

    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_save_find_can_emit_json(single_side: Path) -> None:
    payload = json.loads(
        runner.invoke(app, ["save", "find", str(single_side), str(single_side), "--json"]).stdout
    )

    assert payload["candidates"] == []


def test_save_find_reports_a_candidate(tmp_path: Path) -> None:
    def with_save(fill: int) -> Path:
        content = bytearray(blank_image(sides=1, headered=False, formatted=True))
        content[56:58] = bytes([0x02, 0x01])
        header = (
            bytes([0x03, 0x00, 0x00])
            + b"FC_SAVE "
            + (0x6000).to_bytes(2, "little")
            + (4).to_bytes(2, "little")
            + bytes([0x00])
        )
        content[58:74] = header
        content[74:79] = bytes([0x04]) + bytes([fill]) * 4
        path = tmp_path / f"save{fill}.fds"
        path.write_bytes(bytes(content))
        return path

    result = runner.invoke(app, ["save", "find", str(with_save(1)), str(with_save(2))])

    assert "FC_SAVE" in result.stdout
    assert "name reads like a save" in result.stdout


def test_save_apply_reports_an_unusable_save(single_side: Path, tmp_path: Path) -> None:
    save = tmp_path / "save.bin"
    save.write_bytes(bytes([0x01, 0x02, 0x03]))

    result = runner.invoke(
        app,
        [
            "save",
            "apply",
            str(single_side),
            "--save",
            str(save),
            "-o",
            str(tmp_path / "out.fds"),
        ],
    )

    assert result.exit_code == 1
    assert "not a save" in result.stdout


def test_save_extract_refuses_an_unknown_format(single_side: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "save",
            "extract",
            str(single_side),
            "--played",
            str(single_side),
            "-o",
            str(tmp_path / "out.bin"),
            "--format",
            "unknown",
        ],
    )

    assert result.exit_code == 1
    assert "cannot write" in result.stdout


def test_save_find_as_json_lists_a_candidate(tmp_path: Path) -> None:
    def with_save(fill: int) -> Path:
        content = bytearray(blank_image(sides=1, headered=False, formatted=True))
        content[56:58] = bytes([0x02, 0x01])
        header = (
            bytes([0x03, 0x00, 0x00])
            + b"FC_SAVE "
            + (0x6000).to_bytes(2, "little")
            + (4).to_bytes(2, "little")
            + bytes([0x00])
        )
        content[58:74] = header
        content[74:79] = bytes([0x04]) + bytes([fill]) * 4
        path = tmp_path / f"json-save{fill}.fds"
        path.write_bytes(bytes(content))
        return path

    payload = json.loads(
        runner.invoke(app, ["save", "find", str(with_save(3)), str(with_save(4)), "--json"]).stdout
    )

    assert payload["candidates"][0]["name"] == "FC_SAVE"


def test_save_blank_makes_two_played_copies_agree(tmp_path: Path) -> None:
    one = _save_disk(tmp_path, 0x11, "one.fds")
    two = _save_disk(tmp_path, 0x22, "two.fds")
    recipes = _recipes(tmp_path)

    first = runner.invoke(
        app,
        ["save", "blank", str(one), "-o", str(tmp_path / "a.fds"), "--recipes", str(recipes)],
    )
    second = runner.invoke(
        app,
        ["save", "blank", str(two), "-o", str(tmp_path / "b.fds"), "--recipes", str(recipes)],
    )

    assert first.exit_code == 0
    assert "FC_SAVE" in first.stdout
    assert second.exit_code == 0
    assert (tmp_path / "a.fds").read_bytes() == (tmp_path / "b.fds").read_bytes()


def test_save_blank_says_when_nothing_matched(single_side: Path, tmp_path: Path) -> None:
    recipes = tmp_path / "other.json"
    recipes.write_text(
        json.dumps(
            {
                "version": 1,
                "recipes": [
                    {
                        "game_name": "ZEL",
                        "game_version": 0,
                        "side": 0,
                        "position": 0,
                        "fill": 0,
                        "source": "x",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "save",
            "blank",
            str(single_side),
            "-o",
            str(tmp_path / "out.fds"),
            "--recipes",
            str(recipes),
        ],
    )

    assert result.exit_code == 0
    assert "no recipe matched" in result.stdout


def test_save_blank_reports_a_missing_recipe_file(single_side: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "save",
            "blank",
            str(single_side),
            "-o",
            str(tmp_path / "out.fds"),
            "--recipes",
            str(tmp_path / "nope.json"),
        ],
    )

    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_save_blank_reports_a_recipe_file_that_does_not_parse(
    single_side: Path,
    tmp_path: Path,
) -> None:
    recipes = tmp_path / "bad.json"
    recipes.write_text(json.dumps({"version": 99, "recipes": []}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "save",
            "blank",
            str(single_side),
            "-o",
            str(tmp_path / "out.fds"),
            "--recipes",
            str(recipes),
        ],
    )

    assert result.exit_code == 1
    assert "version" in result.stdout


def test_save_blank_can_write_a_qd(tmp_path: Path) -> None:
    source = _save_disk(tmp_path, 0x33, "played.fds")
    out = tmp_path / "clean.qd"

    result = runner.invoke(
        app,
        ["save", "blank", str(source), "-o", str(out), "--recipes", str(_recipes(tmp_path))],
    )

    assert result.exit_code == 0
    assert out.stat().st_size == 65536


def test_save_apply_needs_the_save_it_applies(single_side: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["save", "apply", str(single_side), "-o", str(tmp_path / "o.fds")])

    assert result.exit_code == 1
    assert "save apply needs --save" in result.stdout


def test_save_extract_needs_an_output(single_side: Path) -> None:
    result = runner.invoke(app, ["save", "extract", str(single_side), "--played", str(single_side)])

    assert result.exit_code == 1
    assert "save extract writes a file, so pass -o" in result.stdout


def test_save_blank_works_on_one_image(single_side: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["save", "blank", str(single_side), str(single_side), "-o", str(tmp_path / "o.fds")]
    )

    assert result.exit_code == 1
    assert "save blank works on one image" in result.stdout


def test_an_unknown_save_action_is_refused(single_side: Path) -> None:
    result = runner.invoke(app, ["save", "erase", str(single_side)])

    assert result.exit_code == 2


def test_save_find_refuses_dumps_of_different_releases(single_side: Path, tmp_path: Path) -> None:
    other = _save_disk(tmp_path, 0x11, "other.fds")

    result = runner.invoke(app, ["save", "find", str(single_side), str(other)])

    assert result.exit_code == 1
    assert "not the same release" in result.stdout
