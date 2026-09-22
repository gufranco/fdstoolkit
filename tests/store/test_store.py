from __future__ import annotations

from pathlib import Path

import pytest

from fdstoolkit.archive.store import Archive, DumpRecord, disk_identity
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side


def _payload(*, serial: int = 0x1234, code: bytes = b"ABC") -> bytes:
    payload = bytearray(56)
    payload[0x00] = BlockKind.DISK_INFO
    payload[0x01:0x0F] = b"*NINTENDO-HVC*"
    payload[0x10:0x13] = code
    payload[0x1F:0x22] = bytes((0x86, 0x02, 0x21))
    payload[0x31:0x33] = serial.to_bytes(2, "little")
    return bytes(payload)


def _disk(**kwargs: object) -> Disk:
    payload = _payload(**kwargs)  # type: ignore[arg-type]
    return Disk(
        sides=(
            Side(
                blocks=(Block(kind=BlockKind.DISK_INFO, payload=payload),),
                tail=b"",
                capacity=65500,
            ),
        )
    )


def _record(disk_id: str, *, taken: str = "2026-09-22", bad: int = 0) -> DumpRecord:
    return DumpRecord(
        disk_id=disk_id,
        taken=taken,
        digest="fdstoolkit:v1:release/v1:abc",
        grade="clean",
        confidence=0.95,
        blocks_total=100,
        blocks_bad=bad,
        drive="AN-500B",
        notes="",
    )


def test_one_physical_disk_hashes_to_a_stable_identity() -> None:
    assert disk_identity(_disk()) == disk_identity(_disk())


def test_two_physical_copies_hash_differently() -> None:
    assert disk_identity(_disk(serial=0x1111)) != disk_identity(_disk(serial=0x2222))


def test_an_unformatted_disk_still_has_an_identity() -> None:
    blank = Disk(sides=(Side(blocks=(), tail=b"", capacity=65500),))

    assert disk_identity(blank)


def test_a_recorded_dump_comes_back_in_the_history(tmp_path: Path) -> None:
    with Archive(tmp_path / "archive.db") as archive:
        archive.record(_record("disk-a"))

        history = archive.history("disk-a")

    assert len(history) == 1
    assert history[0].disk_id == "disk-a"
    assert history[0].grade == "clean"


def test_history_comes_back_oldest_first(tmp_path: Path) -> None:
    with Archive(tmp_path / "archive.db") as archive:
        archive.record(_record("disk-a", taken="2026-09-22"))
        archive.record(_record("disk-a", taken="2024-01-05"))

        history = archive.history("disk-a")

    assert [item.taken for item in history] == ["2024-01-05", "2026-09-22"]


def test_the_archive_lists_every_disk_it_holds(tmp_path: Path) -> None:
    with Archive(tmp_path / "archive.db") as archive:
        archive.record(_record("disk-a"))
        archive.record(_record("disk-b"))

        assert archive.disks() == ("disk-a", "disk-b")


def test_an_unknown_disk_has_an_empty_history(tmp_path: Path) -> None:
    with Archive(tmp_path / "archive.db") as archive:
        assert archive.history("nobody") == ()


def test_the_same_dump_recorded_twice_is_stored_once(tmp_path: Path) -> None:
    with Archive(tmp_path / "archive.db") as archive:
        archive.record(_record("disk-a"))
        archive.record(_record("disk-a"))

        assert len(archive.history("disk-a")) == 1


def test_the_archive_survives_being_reopened(tmp_path: Path) -> None:
    path = tmp_path / "archive.db"
    with Archive(path) as archive:
        archive.record(_record("disk-a"))

    with Archive(path) as reopened:
        assert len(reopened.history("disk-a")) == 1


def test_the_archive_counts_what_it_holds(tmp_path: Path) -> None:
    with Archive(tmp_path / "archive.db") as archive:
        archive.record(_record("disk-a"))
        archive.record(_record("disk-a", taken="2025-01-01"))

        assert archive.dump_count() == 2


def test_using_a_closed_archive_is_refused(tmp_path: Path) -> None:
    archive = Archive(tmp_path / "archive.db")
    archive.close()

    with pytest.raises(ValueError, match="closed"):
        archive.history("disk-a")
