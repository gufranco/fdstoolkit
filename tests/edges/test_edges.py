from __future__ import annotations

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from fdstoolkit.cli.common import decode_image
from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.quality.confidence import ConfidenceReport
from fdstoolkit.quality.reads import ReadStatistics

runner = CliRunner()


def _payload(*, licensee: int = 0) -> bytes:
    payload = bytearray(56)
    payload[0x00] = BlockKind.DISK_INFO
    payload[0x01:0x0F] = b"*NINTENDO-HVC*"
    payload[0x0F] = licensee
    payload[0x10:0x13] = b"ABC"
    return bytes(payload)


def _disk(*, licensee: int = 0) -> Disk:
    return Disk(
        sides=(
            Side(
                blocks=(Block(kind=BlockKind.DISK_INFO, payload=_payload(licensee=licensee)),),
                tail=b"",
                capacity=65500,
            ),
        )
    )


def _write(path: Path, disk: Disk | None = None) -> Path:
    data, _ = fds.encode(disk or _disk(), headered=False)
    path.write_bytes(data)
    return path


def test_a_foreign_image_is_refused(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "foreign.qd"
    path.write_bytes(b"HXCQDDRV" + bytes(65528))

    # Act
    with pytest.raises(typer.Exit) as raised:
        decode_image(path)

    # Assert
    assert raised.type is typer.Exit


def test_an_empty_confidence_report_scores_nothing() -> None:
    # Arrange
    expected = 0.0

    # Act
    result = ConfidenceReport(blocks=()).mean

    # Assert
    assert result == expected


def test_a_statistics_report_with_no_block_is_stable() -> None:
    # Arrange
    expected = 1.0

    # Act
    result = ReadStatistics(passes=2, blocks=()).stability

    # Assert
    assert result == expected


def test_splicing_a_donor_of_another_shape_is_refused(tmp_path: Path) -> None:
    # Arrange
    image = _write(tmp_path / "a.fds")
    other = Disk(
        sides=(
            Side(
                blocks=(
                    Block(kind=BlockKind.DISK_INFO, payload=_payload()),
                    Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([2, 1])),
                ),
                tail=b"",
                capacity=65500,
            ),
        )
    )
    donor = _write(tmp_path / "b.fds", other)

    # Act
    result = runner.invoke(
        app, ["splice", str(image), "--donor", str(donor), "-o", str(tmp_path / "o.fds")]
    )

    # Assert
    assert result.exit_code == 1
    assert "different shape" in result.stdout


def test_grading_against_a_dump_with_another_side_count_is_refused(tmp_path: Path) -> None:
    # Arrange
    image = _write(tmp_path / "a.fds")
    side = Side(
        blocks=(Block(kind=BlockKind.DISK_INFO, payload=_payload()),),
        tail=b"",
        capacity=65500,
    )
    second = _write(tmp_path / "b.fds", Disk(sides=(side, side)))

    # Act
    result = runner.invoke(app, ["grade", str(image), "--read", str(second)])

    # Assert
    assert result.exit_code == 1
    assert "different numbers of sides" in result.stdout
