from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from fdstoolkit.build.blank import blank_image
from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds, qd
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.edit.files import FileSpec, insert_file

runner = CliRunner()


def _payload(*, code: bytes = b"ABC", serial: int = 0xFFFF, licensee: int = 0) -> bytes:
    payload = bytearray(56)
    payload[0x00] = BlockKind.DISK_INFO
    payload[0x01:0x0F] = b"*NINTENDO-HVC*"
    payload[0x0F] = licensee
    payload[0x10:0x13] = code
    payload[0x31:0x33] = serial.to_bytes(2, "little")
    return bytes(payload)


def _disk(
    *,
    code: bytes = b"ABC",
    serial: int = 0xFFFF,
    licensee: int = 0,
    data_byte: int | None = None,
) -> Disk:
    blocks = [
        Block(
            kind=BlockKind.DISK_INFO,
            payload=_payload(code=code, serial=serial, licensee=licensee),
        )
    ]
    if data_byte is not None:
        blocks.append(Block(kind=BlockKind.FILE_DATA, payload=bytes([4, data_byte])))
    return Disk(sides=(Side(blocks=tuple(blocks), tail=b"", capacity=65500),))


def _write_fds(path: Path, disk: Disk) -> Path:
    data, _ = fds.encode(disk, headered=False)
    path.write_bytes(data)
    return path


def _write_qd(path: Path, disk: Disk, *, corrupt: bool = False) -> Path:
    prepared = Disk(
        sides=(
            Side(
                blocks=tuple(
                    (
                        Block(kind=block.kind, payload=block.payload, stored_crc=0x1234)
                        if corrupt
                        else block.with_computed_crc()
                    )
                    for block in disk.sides[0].blocks
                ),
                tail=b"",
                capacity=65536,
            ),
        )
    )
    data, _ = qd.encode(prepared)
    path.write_bytes(data)
    return path


def _corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    _write_fds(root / "a.fds", _disk(serial=0xFFFF))
    _write_fds(root / "b.fds", _disk(serial=0x1234))
    return root


def test_a_missing_path_is_refused_by_name(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["consensus", str(tmp_path / "nowhere"), "-o", str(tmp_path / "out.fds")]
    )

    assert result.exit_code == 1
    assert "not found:" in result.stdout
    assert "nowhere" in result.stdout


def test_dumps_of_one_disk_need_an_output(tmp_path: Path) -> None:
    root = _corpus(tmp_path)

    result = runner.invoke(app, ["consensus", str(root / "a.fds"), str(root / "b.fds")])

    assert result.exit_code == 2


def test_dumps_of_one_disk_can_report_json(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    output = tmp_path / "merged.fds"

    result = runner.invoke(
        app, ["consensus", str(root / "a.fds"), str(root / "a.fds"), "-o", str(output), "--json"]
    )

    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert payload["disagreements"] == []
    assert output.is_file()


def test_a_consensus_written_to_a_qd_file_is_quick_disk(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    output = tmp_path / "merged.qd"

    result = runner.invoke(
        app, ["consensus", str(root / "a.fds"), str(root / "a.fds"), "-o", str(output)]
    )

    assert result.exit_code == 0
    assert output.stat().st_size == qd.SIDE_SIZE


def test_a_bad_block_is_spliced_from_a_donor(tmp_path: Path) -> None:
    broken = _write_qd(tmp_path / "broken.qd", _disk(data_byte=1), corrupt=True)
    donor = _write_qd(tmp_path / "donor.qd", _disk(data_byte=1))
    output = tmp_path / "fixed.fds"

    result = runner.invoke(app, ["splice", str(broken), "--donor", str(donor), "-o", str(output)])

    assert result.exit_code == 0
    assert "taken from donor.qd" in result.stdout
    assert output.is_file()


def test_a_block_with_no_good_donor_is_reported(tmp_path: Path) -> None:
    broken = _write_qd(tmp_path / "broken.qd", _disk(data_byte=1), corrupt=True)
    donor = _write_qd(tmp_path / "donor.qd", _disk(data_byte=1), corrupt=True)
    output = tmp_path / "fixed.fds"

    result = runner.invoke(app, ["splice", str(broken), "--donor", str(donor), "-o", str(output)])

    assert result.exit_code == 1
    assert "no donor carries a good copy" in result.stdout


def test_a_consensus_names_a_block_one_dump_missed(tmp_path: Path) -> None:
    full = insert_file(
        fds.decode(blank_image(sides=1, headered=False, formatted=True))[0],
        side=0,
        spec=FileSpec(name="FILE", address=0x6000, kind=FileKind.PROGRAM, data=bytes(16)),
    )
    side = full.sides[0]
    short = Disk(sides=(Side(blocks=side.blocks[:-2], tail=b"", capacity=side.capacity),))
    paths = [
        _write_fds(tmp_path / name, disk)
        for name, disk in (("a.fds", full), ("b.fds", short), ("c.fds", full))
    ]

    result = runner.invoke(app, ["consensus", *map(str, paths), "-o", str(tmp_path / "o.fds")])
    listed = runner.invoke(
        app, ["consensus", *map(str, paths), "-o", str(tmp_path / "p.fds"), "--json"]
    )

    assert result.exit_code == 0
    assert "missing from 1 dump(s), decided by the others" in result.stdout
    assert len(json.loads(listed.stdout)["missing"]) == 2
