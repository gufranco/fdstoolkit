from __future__ import annotations

from pathlib import Path

import pytest

from fdstoolkit.build.blank import blank_image


@pytest.fixture
def image(tmp_path: Path) -> Path:
    path = tmp_path / "disk.fds"
    path.write_bytes(blank_image(sides=2, headered=False, formatted=True, game_name="SMB"))
    return path


@pytest.fixture
def single_side(tmp_path: Path) -> Path:
    path = tmp_path / "one-side.fds"
    path.write_bytes(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    return path


@pytest.fixture
def damaged(tmp_path: Path) -> Path:
    raw = bytearray(blank_image(sides=1, headered=False, formatted=True))
    raw[1:15] = b"*NOT-NINTENDO*"
    path = tmp_path / "damaged.fds"
    path.write_bytes(bytes(raw))
    return path


@pytest.fixture
def hidden_file_image(tmp_path: Path) -> Path:
    content = bytearray(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    content[56:58] = bytes([0x02, 0x00])
    header = (
        bytes([0x03, 0x00, 0x00])
        + b"SECRET  "
        + (0x6000).to_bytes(2, "little")
        + (4).to_bytes(2, "little")
        + bytes([0x00])
    )
    content[58:74] = header
    content[74:79] = bytes([0x04]) + bytes([0x55]) * 4
    path = tmp_path / "hidden.fds"
    path.write_bytes(bytes(content))
    return path
