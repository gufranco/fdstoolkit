from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app
from fdstoolkit.codecs.qd import encode as encode_qd
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side

if TYPE_CHECKING:
    from faker import Faker
from main_kit import runner


def test_insert_adds_a_file(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "payload.bin"
    payload.write_bytes(bytes([0x42]) * 32)
    out = tmp_path / "with-new.fds"
    arguments = [
        "insert",
        str(single_side),
        "-o",
        str(out),
        "--file",
        str(payload),
        "--name",
        "NEW",
    ]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    listing = runner.invoke(app, ["info", str(out), "--files"])
    assert "NEW" in listing.stdout


def test_insert_refuses_an_address_that_is_not_hex(
    single_side: Path, tmp_path: Path, fake: Faker
) -> None:
    # Arrange
    payload = tmp_path / "payload.bin"
    payload.write_bytes(fake.binary(length=32))
    arguments = ["insert", str(single_side), "-o", str(tmp_path / "out.fds")]
    arguments += ["--file", str(payload), "--name", "NEW", "--address", "zz"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 1
    assert "invalid literal for int() with base 16: 'zz'" in result.stdout


def test_insert_reports_a_name_that_is_too_long(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"\x01")

    # Act
    result = runner.invoke(
        app,
        [
            "insert",
            str(single_side),
            "-o",
            str(tmp_path / "out.fds"),
            "--file",
            str(payload),
            "--name",
            "WAYTOOLONG",
        ],
    )

    # Assert
    assert result.exit_code == 1
    assert "eight characters" in result.stdout


def test_insert_reports_a_missing_file(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    arguments = [
        "insert",
        str(single_side),
        "-o",
        str(tmp_path / "out.fds"),
        "--file",
        str(tmp_path / "nope.bin"),
        "--name",
        "NEW",
    ]

    # Act
    result = runner.invoke(
        app,
        arguments,
    )

    # Assert
    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_insert_can_write_a_qd(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "payload.bin"
    payload.write_bytes(bytes([0x42]) * 8)
    out = tmp_path / "with-new.qd"

    # Act
    result = runner.invoke(
        app,
        [
            "insert",
            str(single_side),
            "-o",
            str(out),
            "--file",
            str(payload),
            "--name",
            "NEW",
        ],
    )

    # Assert
    assert result.exit_code == 0
    assert out.stat().st_size == 65536


def test_insert_reports_a_finding_from_the_encoder(tmp_path: Path) -> None:
    # Arrange
    info = bytearray(56)
    info[0] = 0x01
    info[1:15] = b"*NINTENDO-HVC*"
    size = 65028
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
    source = tmp_path / "nearly-full.qd"
    source.write_bytes(data)
    payload = tmp_path / "payload.bin"
    payload.write_bytes(bytes(400))

    # Act
    result = runner.invoke(
        app,
        [
            "insert",
            str(source),
            "-o",
            str(tmp_path / "out.fds"),
            "--file",
            str(payload),
            "--name",
            "NEW",
        ],
    )

    # Assert
    assert "FDS011" in result.stdout


def test_set_changes_a_field(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "renamed.fds"
    arguments = ["set", str(single_side), "-o", str(out), "--set", "game_name=ZEL"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    assert "game_name: SMB -> ZEL" in result.stdout
    payload = json.loads(runner.invoke(app, ["info", str(out), "--json"]).stdout)
    assert payload["sides"][0]["game_name"] == "ZEL"


def test_set_can_write_a_qd(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "renamed.qd"

    # Act
    result = runner.invoke(
        app,
        ["set", str(single_side), "-o", str(out), "--set", "game_version=2"],
    )

    # Assert
    assert result.exit_code == 0
    assert out.stat().st_size == 65536


def test_set_reports_an_unknown_field(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    arguments = ["set", str(single_side), "-o", str(tmp_path / "o.fds"), "--set", "colour=blue"]

    # Act
    result = runner.invoke(
        app,
        arguments,
    )

    # Assert
    assert result.exit_code == 1
    assert "unknown field" in result.stdout


def test_insert_accepts_a_kind_by_name(tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "chr.bin"
    payload.write_bytes(bytes(16))
    source = tmp_path / "one.fds"
    source.write_bytes(blank_image(sides=1, headered=False, formatted=True))
    built = tmp_path / "built.fds"

    # Act
    result = runner.invoke(
        app,
        [
            "insert",
            str(source),
            "-o",
            str(built),
            "--file",
            str(payload),
            "--name",
            "CHR",
            "--address",
            "0000",
            "--kind",
            "character",
        ],
    )

    # Assert
    assert result.exit_code == 0
    assert "character" in runner.invoke(app, ["info", str(built), "--files"]).stdout


def test_set_refuses_a_date_the_disk_cannot_hold(single_side: Path, tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "dated.fds"
    arguments = ["set", str(single_side), "-o", str(out), "--set", "manufacturing_date=2030-01-01"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 1
    assert "outside 1925 to 2024" in result.output
    assert not out.exists()
