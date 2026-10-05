from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from collections.abc import Mapping
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

from fdstoolkit.build.manifest import build_manifest_file

ROOT: Final = Path(__file__).resolve().parents[1]
SOURCE_DIR: Final = ROOT / "console" / "src"
LINKER_CONFIG: Final = ROOT / "console" / "fdstoolkit-console.cfg"
DEFAULT_BUILD_DIR: Final = ROOT / "console" / "build"
IMAGE_NAME: Final = "fdstoolkit-console.fds"
LIMITS_NAME: Final = "speed_limits.inc"
FONT_NAME: Final = "font.chr"
LABELS_NAME: Final = "labels.txt"

CPU_HZ: Final = Fraction(1_789_773)
BIT_RATE_HZ: Final = Fraction(96_400)
BITS_PER_BYTE: Final = 8
CENTI: Final = 100
RATIO_SCALE: Final = 10_000
BANDS: Final[Mapping[str, Fraction]] = {
    "ULTRA": Fraction(1, 100),
    "FINE": Fraction(5, 100),
    "COARSE": Fraction(10, 100),
}

TILES: Final = 0x60
TILE_BYTES: Final = 16
GLYPH_WIDTH: Final = 5
GLYPH_HEIGHT: Final = 7
GLYPH_COLUMN: Final = 1

GLYPHS: Final[Mapping[str, tuple[str, ...]]] = {
    " ": (".....",) * 7,
    "!": ("..#..", "..#..", "..#..", "..#..", "..#..", ".....", "..#.."),
    "$": ("..#..", ".####", "#.#..", ".###.", "..#.#", "####.", "..#.."),
    "%": ("##...", "##..#", "...#.", "..#..", ".#...", "#..##", "...##"),
    "(": ("...#.", "..#..", ".#...", ".#...", ".#...", "..#..", "...#."),
    ")": (".#...", "..#..", "...#.", "...#.", "...#.", "..#..", ".#..."),
    "+": (".....", "..#..", "..#..", "#####", "..#..", "..#..", "....."),
    ",": (".....", ".....", ".....", ".....", ".##..", "..#..", ".#..."),
    "-": (".....", ".....", ".....", "#####", ".....", ".....", "....."),
    ".": (".....", ".....", ".....", ".....", ".....", ".##..", ".##.."),
    "/": (".....", "....#", "...#.", "..#..", ".#...", "#....", "....."),
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": ("..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."),
    ":": (".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."),
    "?": (".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."),
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."),
    "D": ("###..", "#..#.", "#...#", "#...#", "#...#", "#..#.", "###.."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": (".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".####"),
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": (".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "J": ("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
}

DISK_FILES: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("FTKFONT", "$0000", "Character", FONT_NAME),
    ("FTKMAIN", "$6000", "Program", "console-main.bin"),
    ("FTKVECT", "$DFF6", "Program", "console-vectors.bin"),
    ("FTKBOOT", "$2000", "Program", "console-boot.bin"),
)
OBJECTS: Final = ("main", "screen", "speed", "arithmetic")


def _glyph_tile(rows: tuple[str, ...]) -> bytes:
    plane = bytes(
        sum(1 << (7 - GLYPH_COLUMN - column) for column, cell in enumerate(row) if cell == "#")
        for row in rows
    )
    return plane.ljust(8, b"\0") + bytes(8)


def font_chr() -> bytes:
    blank = bytes(TILE_BYTES)
    return b"".join(
        _glyph_tile(GLYPHS[chr(code)]) if chr(code) in GLYPHS else blank for code in range(TILES)
    )


def speed_limits() -> dict[str, int]:
    nominal = CPU_HZ / (BIT_RATE_HZ / BITS_PER_BYTE) * CENTI
    limits = {
        "NOMINAL_CYCLES_X100": round(nominal),
        "SPEED_RATIO_NUMERATOR": round(nominal * RATIO_SCALE),
    }
    for name, band in BANDS.items():
        limits[f"{name}_FAST_LIMIT"] = math.ceil(nominal / (1 + band))
        limits[f"{name}_SLOW_LIMIT"] = math.floor(nominal / (1 - band))
    return limits


def write_limits(build_dir: Path) -> Path:
    path = build_dir / LIMITS_NAME
    lines = [f"{name} = {value}\n" for name, value in speed_limits().items()]
    path.write_text("".join(lines), encoding="utf-8")
    return path


def manifest(build_dir: Path) -> dict[str, Any]:
    files = [
        {
            "file_number": number,
            "file_indicate_code": number,
            "file_name": name,
            "file_address": address,
            "file_kind": kind,
            "data": str(build_dir / data),
        }
        for number, (name, address, kind, data) in enumerate(DISK_FILES)
    ]
    side = {
        "licensee_code": "$00",
        "game_name": "FTK",
        "disk_side": "A",
        "boot_file": len(files),
        "manufacturing_date": "2026-10-05",
        "country_code": "Japan",
        "file_amount": len(files) + 1,
        "files": files,
    }
    return {"sides": [side]}


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        message = f"{' '.join(command)} failed with {result.returncode}:\n{result.stderr}"
        raise RuntimeError(message)


def _tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        message = f"{name} is not installed; install cc65 to build the console program"
        raise RuntimeError(message)
    return found


def assemble(build_dir: Path) -> None:
    write_limits(build_dir)
    objects = [build_dir / f"{name}.o" for name in OBJECTS]
    for name, target in zip(OBJECTS, objects, strict=True):
        source = SOURCE_DIR / f"{name}.s"
        _run(
            [
                _tool("ca65"),
                "-g",
                "-t",
                "none",
                "-I",
                str(SOURCE_DIR),
                "-I",
                str(build_dir),
                "-o",
                str(target),
                str(source),
            ]
        )
    output = build_dir / "console"
    _run(
        [
            _tool("ld65"),
            "-C",
            str(LINKER_CONFIG),
            "-o",
            str(output),
            "-Ln",
            str(build_dir / LABELS_NAME),
            *(str(target) for target in objects),
        ]
    )


def build(build_dir: Path = DEFAULT_BUILD_DIR) -> Path:
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / FONT_NAME).write_bytes(font_chr())
    assemble(build_dir)
    manifest_path = build_dir / "diskinfo.json"
    manifest_path.write_text(json.dumps(manifest(build_dir), indent=2) + "\n", encoding="utf-8")
    image = build_dir / IMAGE_NAME
    image.write_bytes(build_manifest_file(manifest_path))
    return image


def main() -> int:
    image = build()
    sys.stdout.write(f"wrote {image}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
