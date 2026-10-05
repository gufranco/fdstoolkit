from __future__ import annotations

import importlib.util
import os
import re
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from fdstoolkit.build.fdskey import fdskey_check
from fdstoolkit.codecs.fds import decode
from fdstoolkit.edit.files import extract_files

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_console.py"
TILE_BYTES = 16
REQUIRE_CC65 = os.environ.get("FDSTOOLKIT_REQUIRE_CC65") == "1"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_console", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def console_strings() -> set[str]:
    sources = (ROOT / "console" / "src").glob("*.s")
    found: set[str] = set()
    for source in sources:
        found |= set(re.findall(r'\.byte\s+"([^"]*)"', source.read_text(encoding="utf-8")))
    return found


def test_the_font_holds_one_tile_per_code_up_to_underscore() -> None:
    font: bytes = load_script().font_chr()

    assert len(font) == 0x60 * TILE_BYTES


def test_a_space_is_blank_and_a_digit_is_not() -> None:
    font: bytes = load_script().font_chr()

    space = font[0x20 * TILE_BYTES : 0x21 * TILE_BYTES]
    zero = font[0x30 * TILE_BYTES : 0x31 * TILE_BYTES]
    assert space == bytes(TILE_BYTES)
    assert any(zero[:8])


def test_glyphs_use_only_the_first_bit_plane() -> None:
    font: bytes = load_script().font_chr()

    second_planes = [font[tile + 8 : tile + 16] for tile in range(0, len(font), TILE_BYTES)]
    assert all(plane == bytes(8) for plane in second_planes)


def test_every_character_the_program_prints_has_a_glyph() -> None:
    glyphs: dict[str, Any] = load_script().GLYPHS

    used = {character for text in console_strings() for character in text}

    assert used - set(glyphs) == set()


def test_the_speed_limits_follow_the_nominal_rate() -> None:
    limits: dict[str, int] = load_script().speed_limits()

    assert limits == {
        "NOMINAL_CYCLES_X100": 14853,
        "SPEED_RATIO_NUMERATOR": 148528880,
        "ULTRA_FAST_LIMIT": 14706,
        "ULTRA_SLOW_LIMIT": 15002,
        "FINE_FAST_LIMIT": 14146,
        "FINE_SLOW_LIMIT": 15634,
        "COARSE_FAST_LIMIT": 13503,
        "COARSE_SLOW_LIMIT": 16503,
    }


def test_the_limits_are_written_as_assembler_constants(tmp_path: Path) -> None:
    script = load_script()

    path = script.write_limits(tmp_path)

    text = path.read_text(encoding="utf-8")
    assert "ULTRA_FAST_LIMIT = 14706\n" in text
    assert "SPEED_RATIO_NUMERATOR = 148528880\n" in text


def test_the_manifest_declares_one_file_more_than_it_carries(tmp_path: Path) -> None:
    manifest: dict[str, Any] = load_script().manifest(tmp_path)

    side = manifest["sides"][0]
    assert side["file_amount"] == len(side["files"]) + 1
    assert [item["file_address"] for item in side["files"]] == ["$0000", "$6000", "$DFF6", "$2000"]
    assert side["files"][-1]["file_name"] == "FTKBOOT"


needs_cc65 = pytest.mark.skipif(
    shutil.which("ca65") is None and not REQUIRE_CC65,
    reason="cc65 is not installed; CI sets FDSTOOLKIT_REQUIRE_CC65=1 so it never skips there",
)


@needs_cc65
def test_the_program_builds_into_a_disk_fdskey_loads(tmp_path: Path) -> None:
    image = load_script().build(tmp_path)

    disk, findings = decode(image.read_bytes())

    files = extract_files(disk)
    assert [entry.address for entry in files] == [0x0000, 0x6000, 0xDFF6, 0x2000]
    assert files[-1].data == bytes([0x90])
    assert fdskey_check(disk).refusals == ()
    assert [finding.code for finding in findings] == ["FDS009"]


@needs_cc65
def test_the_vectors_point_into_the_program(tmp_path: Path) -> None:
    image = load_script().build(tmp_path)

    disk, _ = decode(image.read_bytes())

    files = extract_files(disk)
    program, vectors = files[1], files[2]
    end = 0x6000 + program.size
    words = [int.from_bytes(vectors.data[i : i + 2], "little") for i in range(0, 10, 2)]
    assert all(0x6000 <= word < end for word in words)
