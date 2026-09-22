from __future__ import annotations

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError
from fdstoolkit.hardware.simulation import FaultPlan, SimulatedDrive


def sample_disk(sides: int = 1):  # noqa: ANN201
    disk, _ = decode(blank_image(sides=sides, headered=False, formatted=True, game_name="SMB"))
    return disk


def test_a_drive_with_a_disk_is_ready() -> None:
    drive = SimulatedDrive(sample_disk())

    assert drive.status().can_read
    assert drive.status().can_write


def test_an_empty_drive_reports_no_disk() -> None:
    drive = SimulatedDrive(None)

    assert not drive.status().can_read


def test_reading_returns_every_block_of_the_side() -> None:
    drive = SimulatedDrive(sample_disk())

    blocks = list(drive.read_side(0))

    assert [block.payload[0] for block in blocks] == [0x01, 0x02]
    assert all(block.crc_ok for block in blocks)


def test_reading_an_empty_drive_raises_a_media_fault() -> None:
    drive = SimulatedDrive(None)

    with pytest.raises(HardwareFaultError) as caught:
        list(drive.read_side(0))

    assert caught.value.kind is FaultKind.MEDIA


def test_a_block_can_be_planned_to_fail_its_crc() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(bad_crc_blocks=frozenset({1})))

    blocks = list(drive.read_side(0))

    assert blocks[0].crc_ok
    assert not blocks[1].crc_ok


def test_a_flaky_block_succeeds_after_the_planned_attempts() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(flaky_blocks={1: 3}))

    first = list(drive.read_side(0))
    second = list(drive.read_side(0))
    third = list(drive.read_side(0))

    assert not first[1].crc_ok
    assert not second[1].crc_ok
    assert third[1].crc_ok


def test_an_unstable_block_returns_different_bytes_each_read() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(unstable_blocks=frozenset({1})))

    first = list(drive.read_side(0))
    second = list(drive.read_side(0))

    assert first[1].payload != second[1].payload


def test_the_link_can_drop_partway_through_a_read() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(link_lost_after=1))

    with pytest.raises(HardwareFaultError) as caught:
        list(drive.read_side(0))

    assert caught.value.kind is FaultKind.LINK


def test_writing_stores_the_blocks_and_they_read_back() -> None:
    drive = SimulatedDrive(sample_disk())
    payloads = [bytes([0x01]) + bytes(55), bytes([0x02, 0x00])]

    drive.write_side(0, payloads)

    assert [block.payload for block in drive.read_side(0)] == payloads


def test_writing_to_a_protected_disk_is_refused() -> None:
    drive = SimulatedDrive(sample_disk(), write_protected=True)

    with pytest.raises(HardwareFaultError) as caught:
        drive.write_side(0, [bytes([0x02, 0x00])])

    assert caught.value.kind is FaultKind.PROTECTED


def test_a_write_that_does_not_stick_is_simulated() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(writes_do_not_stick=True))
    before = [block.payload for block in drive.read_side(0)]

    drive.write_side(0, [bytes([0x02, 0x00])])

    assert [block.payload for block in drive.read_side(0)] == before


def test_reading_an_unknown_side_is_a_media_fault() -> None:
    drive = SimulatedDrive(sample_disk(sides=1))

    with pytest.raises(HardwareFaultError):
        list(drive.read_side(4))


def test_the_drive_counts_what_it_was_asked_to_do() -> None:
    drive = SimulatedDrive(sample_disk())

    list(drive.read_side(0))
    list(drive.read_side(0))

    assert drive.read_count == 2


def test_a_flat_battery_blocks_a_write() -> None:
    drive = SimulatedDrive(sample_disk(), battery_ok=False)

    with pytest.raises(HardwareFaultError, match="battery"):
        drive.write_side(0, [bytes([0x02, 0x00])])
