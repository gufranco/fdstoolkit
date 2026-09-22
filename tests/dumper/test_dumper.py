from __future__ import annotations

from collections import deque

import pytest

from fdstk.build.blank import blank_image
from fdstk.codecs.fds import decode
from fdstk.core.disk import Disk
from fdstk.hardware.dumper import (
    MIN_PROTOCOL_VERSION,
    Command,
    FamicomDumper,
    Packet,
)
from fdstk.hardware.ports import FaultKind, HardwareFaultError


class FakeLink:
    def __init__(self, packets: deque[Packet] | None = None, *, version: int = 3) -> None:
        self.sent: list[Packet] = []
        self.packets = packets or deque()
        self.version = version
        self.closed = False

    def protocol_version(self) -> int:
        return self.version

    def send(self, packet: Packet) -> None:
        self.sent.append(packet)

    def receive(self) -> Packet:
        if not self.packets:
            message = "the dumper stopped answering"
            raise HardwareFaultError(message, kind=FaultKind.LINK)
        return self.packets.popleft()

    def close(self) -> None:
        self.closed = True


def sample_disk() -> Disk:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    return disk


def read_packets(disk: Disk, *, crc_ok: bool = True) -> deque[Packet]:
    packets: deque[Packet] = deque()
    blocks = disk.sides[0].blocks
    for index, block in enumerate(blocks):
        last = index == len(blocks) - 1
        packets.append(
            Packet(
                command=Command.READ_RESULT_BLOCK,
                payload=block.payload + bytes([1 if crc_ok else 0, 1 if last else 0]),
            )
        )
    packets.append(Packet(command=Command.READ_RESULT_END, payload=b""))
    return packets


def test_the_command_values_are_the_documented_ones() -> None:
    assert Command.FDS_READ_REQUEST == 45
    assert Command.READ_RESULT_BLOCK == 46
    assert Command.READ_RESULT_END == 47
    assert Command.WRITE_REQUEST == 53
    assert Command.WRITE_DONE == 54
    assert Command.DISK_WRITE_PROTECTED == 57
    assert Command.BLOCK_CRC_ERROR == 58


def test_an_old_protocol_version_is_refused() -> None:
    with pytest.raises(HardwareFaultError, match="protocol version"):
        FamicomDumper(FakeLink(version=MIN_PROTOCOL_VERSION - 1))


def test_reading_a_side_asks_for_it_first() -> None:
    link = FakeLink(read_packets(sample_disk()))

    list(FamicomDumper(link).read_side(0))

    assert link.sent[0].command is Command.FDS_READ_REQUEST


def test_reading_a_side_yields_every_block() -> None:
    disk = sample_disk()
    link = FakeLink(read_packets(disk))

    blocks = list(FamicomDumper(link).read_side(0))

    assert [block.payload for block in blocks] == [block.payload for block in disk.sides[0].blocks]
    assert all(block.crc_ok for block in blocks)


def test_a_block_the_dumper_marks_bad_is_reported_as_failing() -> None:
    link = FakeLink(read_packets(sample_disk(), crc_ok=False))

    blocks = list(FamicomDumper(link).read_side(0))

    assert all(block.failed for block in blocks)


def test_a_crc_error_packet_stops_the_read() -> None:
    packets: deque[Packet] = deque([Packet(command=Command.BLOCK_CRC_ERROR, payload=b"")])
    link = FakeLink(packets)

    with pytest.raises(HardwareFaultError) as caught:
        list(FamicomDumper(link).read_side(0))

    assert caught.value.kind is FaultKind.MEDIA


def test_a_missing_disk_is_reported() -> None:
    packets: deque[Packet] = deque([Packet(command=Command.DISK_NOT_INSERTED, payload=b"")])
    link = FakeLink(packets)

    with pytest.raises(HardwareFaultError, match="no disk"):
        list(FamicomDumper(link).read_side(0))


def test_a_timeout_packet_is_a_timeout_fault() -> None:
    packets: deque[Packet] = deque([Packet(command=Command.TIMEOUT, payload=b"")])
    link = FakeLink(packets)

    with pytest.raises(HardwareFaultError) as caught:
        list(FamicomDumper(link).read_side(0))

    assert caught.value.kind is FaultKind.TIMEOUT


def test_a_disconnected_adapter_is_a_link_fault() -> None:
    packets: deque[Packet] = deque([Packet(command=Command.NOT_CONNECTED, payload=b"")])
    link = FakeLink(packets)

    with pytest.raises(HardwareFaultError) as caught:
        list(FamicomDumper(link).read_side(0))

    assert caught.value.kind is FaultKind.LINK


def test_the_status_reports_what_the_dumper_last_saw() -> None:
    link = FakeLink(read_packets(sample_disk()))
    dumper = FamicomDumper(link)

    assert dumper.status().can_read
    assert dumper.reports_write_protection


def test_a_low_battery_packet_marks_the_status() -> None:
    packets: deque[Packet] = deque([Packet(command=Command.BATTERY_LOW, payload=b"")])
    dumper = FamicomDumper(FakeLink(packets))

    with pytest.raises(HardwareFaultError, match="battery"):
        list(dumper.read_side(0))

    assert not dumper.status().battery_ok


def test_a_write_protected_disk_marks_the_status() -> None:
    packets: deque[Packet] = deque([Packet(command=Command.DISK_WRITE_PROTECTED, payload=b"")])
    dumper = FamicomDumper(FakeLink(packets))

    with pytest.raises(HardwareFaultError, match="write protected"):
        dumper.write_side(0, [bytes([0x02, 0x00])])

    assert dumper.status().write_protected


def test_writing_sends_one_request_per_block_and_waits_for_done() -> None:
    packets: deque[Packet] = deque([Packet(command=Command.WRITE_DONE, payload=b"")])
    link = FakeLink(packets)
    disk = sample_disk()

    FamicomDumper(link).write_side(0, [block.payload for block in disk.sides[0].blocks])

    assert [packet.command for packet in link.sent] == [Command.WRITE_REQUEST] * 2


def test_a_write_that_never_completes_is_a_link_fault() -> None:
    link = FakeLink(deque())

    with pytest.raises(HardwareFaultError):
        FamicomDumper(link).write_side(0, [bytes([0x02, 0x00])])


def test_closing_releases_the_link() -> None:
    link = FakeLink()

    FamicomDumper(link).close()

    assert link.closed


def test_an_unexpected_command_during_a_read_is_a_link_fault() -> None:
    packets: deque[Packet] = deque([Packet(command=Command.END_OF_HEAD, payload=b"")])

    with pytest.raises(HardwareFaultError, match="unexpected command"):
        list(FamicomDumper(FakeLink(packets)).read_side(0))


def test_a_write_answered_with_the_wrong_command_is_a_link_fault() -> None:
    packets: deque[Packet] = deque([Packet(command=Command.END_OF_HEAD, payload=b"")])

    with pytest.raises(HardwareFaultError, match="did not confirm"):
        FamicomDumper(FakeLink(packets)).write_side(0, [bytes([0x02, 0x00])])


def test_a_read_ends_at_the_end_of_head_flag() -> None:
    disk = sample_disk()
    packets = read_packets(disk)
    packets.pop()

    blocks = list(FamicomDumper(FakeLink(packets)).read_side(0))

    assert len(blocks) == len(disk.sides[0].blocks)


def test_a_read_ends_on_the_end_packet_when_no_block_flags_it() -> None:
    disk = sample_disk()
    packets: deque[Packet] = deque(
        Packet(command=Command.READ_RESULT_BLOCK, payload=block.payload + bytes([1, 0]))
        for block in disk.sides[0].blocks
    )
    packets.append(Packet(command=Command.READ_RESULT_END, payload=b""))

    blocks = list(FamicomDumper(FakeLink(packets)).read_side(0))

    assert len(blocks) == len(disk.sides[0].blocks)
