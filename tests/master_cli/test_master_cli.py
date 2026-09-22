from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds, qd
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side

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


def test_a_corpus_of_agreeing_dumps_is_unanimous(tmp_path: Path) -> None:
    result = runner.invoke(app, ["masters", str(_corpus(tmp_path))])

    assert result.exit_code == 0
    assert "unanimous     1 of 1" in result.stdout


def test_a_contested_game_is_named(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    _write_fds(root / "c.fds", _disk(licensee=0x99))

    result = runner.invoke(app, ["masters", str(root), "--json"])

    payload = json.loads(result.stdout)
    assert result.exit_code == 1
    assert payload["dumps"] == 3


def test_an_empty_directory_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    result = runner.invoke(app, ["masters", str(empty)])

    assert result.exit_code == 1
    assert "no image found" in result.stdout


def test_a_missing_directory_is_refused(tmp_path: Path) -> None:
    result = runner.invoke(app, ["masters", str(tmp_path / "nowhere")])

    assert result.exit_code == 1
    assert "directory not found" in result.stdout


def test_an_unknown_profile_is_refused(tmp_path: Path) -> None:
    result = runner.invoke(app, ["masters", str(_corpus(tmp_path)), "--profile", "nope"])

    assert result.exit_code == 1
    assert "unknown profile" in result.stdout


def test_a_reference_set_is_built_and_verified(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    reference = tmp_path / "set.json"

    built = runner.invoke(
        app,
        ["reference-build", str(root), "-o", str(reference), "--set-version", "1"],
    )
    assert built.exit_code == 0
    assert reference.is_file()

    checked = runner.invoke(app, ["reference-verify", str(root / "a.fds"), "--set", str(reference)])
    assert checked.exit_code == 0
    assert "match" in checked.stdout


def test_an_image_outside_the_set_is_unknown(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    reference = tmp_path / "set.json"
    runner.invoke(app, ["reference-build", str(root), "-o", str(reference), "--set-version", "1"])
    other = _write_fds(tmp_path / "z.fds", _disk(code=b"ZZZ"))

    result = runner.invoke(app, ["reference-verify", str(other), "--set", str(reference), "--json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["verdict"] == "unknown"


def test_verifying_against_a_missing_set_is_refused(tmp_path: Path) -> None:
    root = _corpus(tmp_path)

    result = runner.invoke(
        app, ["reference-verify", str(root / "a.fds"), "--set", str(tmp_path / "no.json")]
    )

    assert result.exit_code == 1
    assert "file not found" in result.stdout


def test_verifying_against_a_bad_set_is_refused(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema": "other"}', encoding="utf-8")

    result = runner.invoke(app, ["reference-verify", str(root / "a.fds"), "--set", str(bad)])

    assert result.exit_code == 1


def test_a_dat_is_emitted_from_a_corpus(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    output = tmp_path / "set.dat"

    result = runner.invoke(
        app,
        ["dat-build", str(root), "-o", str(output), "--name", "FDS", "--set-version", "1"],
    )

    assert result.exit_code == 0
    assert "<datafile>" in output.read_text(encoding="utf-8")


def test_a_dat_from_an_empty_directory_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    result = runner.invoke(
        app,
        [
            "dat-build",
            str(empty),
            "-o",
            str(tmp_path / "out.dat"),
            "--name",
            "FDS",
            "--set-version",
            "1",
        ],
    )

    assert result.exit_code == 1
    assert "at least one entry" in result.stdout


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
