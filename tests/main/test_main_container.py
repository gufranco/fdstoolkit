from __future__ import annotations

from pathlib import Path

import click
import pytest
from main_kit import game_with_a_file, runner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds
from fdstoolkit.codecs.qd import encode as encode_qd
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import SIDE_SIZE, Disk, Side


def test_convert_writes_a_qd(image: Path, tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "disk.qd"

    # Act
    result = runner.invoke(app, ["convert", str(image), "-o", str(out)])

    # Assert
    assert result.exit_code == 0
    assert out.stat().st_size == 2 * 65536


def test_convert_round_trips_back_to_fds(image: Path, tmp_path: Path) -> None:
    # Arrange
    as_qd = tmp_path / "disk.qd"
    back = tmp_path / "back.fds"
    runner.invoke(app, ["convert", str(image), "-o", str(as_qd)])

    # Act
    runner.invoke(app, ["convert", str(as_qd), "-o", str(back)])

    # Assert
    assert back.read_bytes() == image.read_bytes()


def test_convert_refuses_to_overwrite_without_force(image: Path, tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "taken.qd"
    out.write_bytes(b"existing")

    # Act
    result = runner.invoke(app, ["convert", str(image), "-o", str(out)])

    # Assert
    assert result.exit_code == 1
    assert out.read_bytes() == b"existing"


def test_convert_overwrites_when_forced(image: Path, tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "taken.qd"
    out.write_bytes(b"existing")

    # Act
    result = runner.invoke(app, ["convert", str(image), "-o", str(out), "--force"])

    # Assert
    assert result.exit_code == 0
    assert out.read_bytes() != b"existing"


@pytest.mark.parametrize("suffix", [".fds", ".qd"])
def test_an_image_bundling_more_than_one_disk_is_refused(tmp_path: Path, suffix: str) -> None:
    # Arrange
    bundle = tmp_path / f"bundle{suffix}"
    three = blank_image(sides=2, headered=False, formatted=True) + blank_image(
        sides=1, headered=False, formatted=True
    )
    bundle.write_bytes(
        three
        if suffix == ".fds"
        else encode_qd(fds.decode(three[: 2 * SIDE_SIZE])[0])[0]
        + encode_qd(fds.decode(three[2 * SIDE_SIZE :])[0])[0]
    )

    # Act
    result = runner.invoke(app, ["info", str(bundle)])

    # Assert
    assert result.exit_code == 1
    assert "holds 3 sides" in result.output
    assert "one disk per image" in result.output


def test_blank_writes_the_reference_image(tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "blank64.fds"

    # Act
    result = runner.invoke(app, ["blank", "-o", str(out), "--sides", "1", "--header"])

    # Assert
    assert result.exit_code == 0
    assert out.stat().st_size == 16 + SIDE_SIZE


@pytest.mark.parametrize("command", ["blank", "dump", "surface"])
@pytest.mark.parametrize("sides", ["0", "3", "-1", "1.5", "2.0", "two"])
def test_a_side_count_other_than_one_or_two_is_refused(
    command: str, sides: str, tmp_path: Path
) -> None:
    # Arrange
    output = ["-o", str(tmp_path / "x.fds")] if command != "surface" else []

    # Act
    result = runner.invoke(app, [command, *output, "--sides", sides])

    # Assert
    assert result.exit_code == 2
    assert "--sides" in click.unstyle(result.output)


def test_blank_can_write_a_formatted_disk(tmp_path: Path) -> None:
    # Arrange
    out = tmp_path / "formatted.fds"

    # Act
    runner.invoke(app, ["blank", "-o", str(out), "--sides", "2", "--formatted"])

    # Assert
    assert runner.invoke(app, ["verify", str(out)]).exit_code == 0


def test_a_missing_file_is_reported_without_a_traceback(tmp_path: Path) -> None:
    # Arrange
    arguments = ["info", str(tmp_path / "nope.fds")]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_an_unknown_extension_is_reported(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "disk.bin"
    path.write_bytes(bytes(SIDE_SIZE))

    # Act
    result = runner.invoke(app, ["info", str(path)])

    # Assert
    assert result.exit_code == 1
    assert "format" in result.stdout


def test_convert_reports_a_side_that_will_not_fit_the_target(tmp_path: Path) -> None:
    # Arrange
    info = bytearray(56)
    info[0] = 0x01
    info[1:15] = b"*NINTENDO-HVC*"
    size = 65450
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
    source = tmp_path / "big.qd"
    source.write_bytes(data)
    out = tmp_path / "big.fds"

    # Act
    result = runner.invoke(app, ["convert", str(source), "-o", str(out)])

    # Assert
    assert result.exit_code == 1
    assert "FDS011" in result.stdout


def test_blank_reports_an_invalid_game_name(tmp_path: Path) -> None:
    # Arrange
    arguments = ["blank", "-o", str(tmp_path / "b.fds"), "--game-name", "TOOLONG"]

    # Act
    result = runner.invoke(
        app,
        arguments,
    )

    # Assert
    assert result.exit_code == 1
    assert "three characters" in result.stdout


def test_an_everdrive_save_is_read_as_a_headerless_image(tmp_path: Path) -> None:
    # Arrange
    source = tmp_path / "bram.srm"
    source.write_bytes(game_with_a_file(tmp_path).read_bytes())

    # Act
    result = runner.invoke(app, ["info", str(source)])

    # Assert
    assert result.exit_code == 0
    assert "bram.srm: fds container, 2 side(s)" in result.stdout


def test_a_cartridge_save_named_srm_is_refused_with_the_reason(tmp_path: Path) -> None:
    # Arrange
    source = tmp_path / "Zelda.srm"
    source.write_bytes(bytes(8192))

    # Act
    result = runner.invoke(app, ["info", str(source)])

    # Assert
    assert result.exit_code == 1
    assert "Zelda.srm is not a Famicom Disk System save" in result.stdout
    assert "8192 bytes" in result.stdout


def test_a_disk_converts_to_an_everdrive_save(tmp_path: Path) -> None:
    # Arrange
    source = game_with_a_file(tmp_path)
    output = tmp_path / "bram.srm"

    # Act
    result = runner.invoke(app, ["convert", str(source), "-o", str(output)])

    # Assert
    assert result.exit_code == 0
    assert output.read_bytes() == source.read_bytes()


def test_an_everdrive_save_never_takes_a_header(tmp_path: Path) -> None:
    # Arrange
    source = game_with_a_file(tmp_path)

    # Act
    result = runner.invoke(
        app, ["convert", str(source), "-o", str(tmp_path / "bram.srm"), "--header"]
    )

    # Assert
    assert result.exit_code == 1
    assert "an .srm save is headerless" in result.stdout


def test_a_sharp_mz_disk_is_refused_by_name(tmp_path: Path) -> None:
    # Arrange
    source = tmp_path / "mz.qd"
    source.write_bytes(b"-QD format-" + b"\xff" * 5 + bytes(81920))

    # Act
    result = runner.invoke(app, ["info", str(source)])

    # Assert
    assert result.exit_code == 1
    assert "Sharp MZ Quick Disk image in QDF form, not a Famicom" in result.stdout
