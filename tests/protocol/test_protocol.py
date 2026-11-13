from __future__ import annotations

import pytest
from device import ID_FINISH_WRITE, UNPLUGGED, FakeFdsStick

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.raw import encode_block_stream, encode_raw03
from fdstoolkit.codecs.write_stream import encode_write_stream
from fdstoolkit.core.disk import Disk
from fdstoolkit.hardware.fdsstick import (
    BLANKED_PACKETS,
    CHUNK_PAYLOAD,
    LEAD_IN_PACKETS,
    LEGACY_REPORTS,
    MODE_READ,
    MODE_WRITE,
    PRODUCT_ID,
    RAW_SIDE_LIMIT,
    READS_AFTER_WRITE,
    SETTLE_PAUSE_S,
    VENDOR_ID,
    WRITE_PAYLOAD,
    WRITE_STARTS,
    DriveNotReadyError,
    FdsStick,
    HidApiTransport,
    NothingReadError,
    ReportId,
)
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError
from fdstoolkit.hardware.session import WriteNotTakenError, write_verified

FLASH_REPORTS = frozenset({0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09})
EMULATOR_REPORTS = frozenset({0x21, 0x22, 0x23})
FINISH = bytes([0x20, 0x00])
WRITE_REPORT_LENGTH = 0x100
PACKETS_PAST_THE_WRAP = 300
FACTORY_FILL = bytes([0x75, 0x5D, 0xD7])
FILLS_PER_PACKET = 85


def raw_side(packets: int = PACKETS_PAST_THE_WRAP) -> bytes:
    return bytes(range(256)) * (packets * CHUNK_PAYLOAD // 256 + 1)


def stick_over(device: FakeFdsStick, pauses: list[float] | None = None) -> FdsStick:
    taken = pauses if pauses is not None else []
    return FdsStick(HidApiTransport(device), pause=taken.append)


def test_the_device_is_the_one_both_reference_tools_open() -> None:
    # Arrange
    expected = (0x16D0, 0x0AAA)

    # Act
    result = (VENDOR_ID, PRODUCT_ID)

    # Assert
    assert result == expected


def test_the_driver_knows_only_the_reports_that_reach_a_real_drive() -> None:
    # Arrange
    expected = {0x10, 0x11, 0x12, 0x20}

    # Act
    result = {int(report) for report in ReportId}

    # Assert
    assert result == expected


def test_a_whole_side_comes_back_byte_for_byte() -> None:
    # Arrange
    side = raw_side()[: 12 * CHUNK_PAYLOAD]

    # Act
    device = FakeFdsStick(side=side)

    # Assert
    assert stick_over(device).read_raw_side() == side


def test_a_side_long_enough_to_wrap_the_counter_still_comes_back_whole() -> None:
    # Arrange
    side = raw_side()
    device = FakeFdsStick(side=side)

    # Act
    read = stick_over(device).read_raw_side()

    # Assert
    assert device.served > 0xFF
    assert read == side


def test_a_read_that_wraps_reports_no_lost_data() -> None:
    # Arrange
    device = FakeFdsStick(side=raw_side())
    stick = stick_over(device)

    # Act
    stick.read_raw_side()

    # Assert
    assert stick.resyncs == ()


def test_a_stale_first_reply_is_dropped_rather_than_stored() -> None:
    # Arrange
    side = raw_side()[: 4 * CHUNK_PAYLOAD]

    # Act
    device = FakeFdsStick(side=side, stale_first=0x7A)

    # Assert
    assert stick_over(device).read_raw_side() == side


def test_a_stale_first_reply_takes_the_first_packet_slot_without_counting_a_skip() -> None:
    # Arrange
    device = FakeFdsStick(side=raw_side()[: 4 * CHUNK_PAYLOAD], stale_first=0x7A)
    stick = stick_over(device)

    # Act
    stick.read_raw_side()

    # Assert
    assert stick.resyncs == ()


def test_a_packet_lost_after_a_stale_first_reply_is_still_counted() -> None:
    # Arrange
    device = FakeFdsStick(side=raw_side()[: 8 * CHUNK_PAYLOAD], stale_first=0x7A, drop_after=3)
    stick = stick_over(device)

    # Act
    stick.read_raw_side()

    # Assert
    assert stick.resyncs == ((5, 6),)


def test_a_dropped_packet_does_not_abandon_the_dump() -> None:
    # Arrange
    side = raw_side()[: 8 * CHUNK_PAYLOAD]

    # Act
    device = FakeFdsStick(side=side, drop_after=3)

    # Assert
    assert stick_over(device).read_raw_side() == side


def test_a_dropped_packet_is_recorded_so_the_read_can_be_judged() -> None:
    # Arrange
    device = FakeFdsStick(side=raw_side()[: 8 * CHUNK_PAYLOAD], drop_after=3)
    stick = stick_over(device)

    # Act
    stick.read_raw_side()

    # Assert
    assert stick.resyncs == ((5, 6),)


def test_a_side_that_ends_mid_chunk_keeps_its_last_bytes() -> None:
    # Arrange
    side = raw_side()[: 3 * CHUNK_PAYLOAD + 17]

    # Act
    device = FakeFdsStick(side=side)

    # Assert
    assert stick_over(device).read_raw_side() == side


def test_a_device_that_pads_the_last_chunk_still_ends_the_side() -> None:
    # Arrange
    side = raw_side()[: 3 * CHUNK_PAYLOAD]

    # Act
    device = FakeFdsStick(side=side, pads_last_chunk=True)

    # Assert
    assert stick_over(device).read_raw_side() == side


def test_a_reply_too_short_to_carry_a_sequence_is_a_link_fault() -> None:
    # Arrange
    device = FakeFdsStick(side=raw_side(), short_reply=True)

    # Act
    with pytest.raises(HardwareFaultError) as raised:
        stick_over(device).read_raw_side()

    # Assert
    assert raised.type is HardwareFaultError
    assert raised.value.kind is FaultKind.LINK


def test_a_disk_that_never_ends_stops_at_the_raw_ceiling() -> None:
    # Arrange
    side = bytes(RAW_SIDE_LIMIT * 2)

    # Act
    device = FakeFdsStick(side=side)

    # Assert
    assert len(stick_over(device).read_raw_side()) >= RAW_SIDE_LIMIT


def test_a_read_arms_the_device_in_read_mode() -> None:
    # Arrange
    device = FakeFdsStick(side=raw_side()[:CHUNK_PAYLOAD])

    # Act
    stick_over(device).read_raw_side()

    # Assert
    assert device.starts == [MODE_READ]


def test_a_write_arms_the_device_in_write_mode() -> None:
    # Arrange
    device = FakeFdsStick()

    # Act
    stick_over(device).write_raw_side(bytes(WRITE_PAYLOAD))

    # Assert
    assert device.starts == [MODE_WRITE]


def test_everything_handed_to_a_write_reaches_the_device() -> None:
    # Arrange
    body = raw_side()[: 5 * WRITE_PAYLOAD]
    device = FakeFdsStick()

    # Act
    stick_over(device).write_raw_side(body)

    # Assert
    assert bytes(device.written) == body


def test_a_short_final_write_is_padded_to_a_whole_report() -> None:
    # Arrange
    device = FakeFdsStick()

    # Act
    stick_over(device).write_raw_side(bytes(10))

    # Assert
    assert len(device.written) == WRITE_PAYLOAD


def test_a_device_that_stops_early_is_a_link_fault() -> None:
    # Arrange
    device = FakeFdsStick(accepts_writes=3)

    # Act
    with pytest.raises(HardwareFaultError) as raised:
        stick_over(device).write_raw_side(bytes(WRITE_PAYLOAD * 10))

    # Assert
    assert raised.type is DriveNotReadyError
    assert raised.value.kind is FaultKind.LINK


def test_a_write_the_drive_was_not_ready_for_is_started_again_after_a_pause() -> None:
    # Arrange
    body = raw_side()[: 30 * WRITE_PAYLOAD]
    device = FakeFdsStick(unready_sessions=2)
    pauses: list[float] = []

    # Act
    stick_over(device, pauses).write_raw_side(body)

    # Assert
    assert bytes(device.written) == body
    assert device.starts == [MODE_WRITE] * 3
    assert pauses == [SETTLE_PAUSE_S] * 2


def test_a_drive_never_ready_to_write_is_a_link_fault_after_every_start() -> None:
    # Arrange
    device = FakeFdsStick(unready_sessions=WRITE_STARTS)

    # Act
    with pytest.raises(HardwareFaultError, match="never became ready") as raised:
        stick_over(device).write_raw_side(bytes(WRITE_PAYLOAD * 30))

    # Assert
    assert raised.type is DriveNotReadyError
    assert raised.value.kind is FaultKind.LINK
    assert device.starts == [MODE_WRITE] * WRITE_STARTS


def test_a_device_that_stops_after_the_lead_in_is_not_started_again() -> None:
    # Arrange
    device = FakeFdsStick(accepts_writes=LEAD_IN_PACKETS)

    # Act
    with pytest.raises(HardwareFaultError, match="stopped accepting data") as raised:
        stick_over(device).write_raw_side(bytes(WRITE_PAYLOAD * (LEAD_IN_PACKETS + 5)))

    # Assert
    assert raised.type is HardwareFaultError
    assert raised.value.kind is FaultKind.LINK
    assert device.starts == [MODE_WRITE]


def test_a_device_that_stops_once_the_disk_has_turned_is_not_a_fault() -> None:
    # Arrange
    body = raw_side()[: (LEAD_IN_PACKETS + 5) * WRITE_PAYLOAD]
    device = FakeFdsStick(accepts_writes=LEAD_IN_PACKETS + 8)

    # Act
    stick_over(device).write_raw_side(body, fill_to=LEAD_IN_PACKETS + 20)

    # Assert
    assert bytes(device.written) == body + FACTORY_FILL * (3 * FILLS_PER_PACKET)
    assert device.finishes == [bytes([ID_FINISH_WRITE, 0x00])]


def test_a_device_that_stops_inside_the_image_says_how_much_was_written() -> None:
    # Arrange
    device = FakeFdsStick(accepts_writes=LEAD_IN_PACKETS + 3)

    # Act
    with pytest.raises(HardwareFaultError, match="after 20 of 40 packet") as raised:
        stick_over(device).write_raw_side(bytes(WRITE_PAYLOAD * 40), fill_to=60)

    # Assert
    assert raised.type is HardwareFaultError
    assert raised.value.kind is FaultKind.LINK
    assert "only part of the image" in str(raised.value)


def test_a_side_written_from_blocks_is_filled_to_the_end_of_the_track() -> None:
    # Arrange
    disk = decode(blank_image(sides=1, headered=False, formatted=True, game_name="PAD"))[0]
    blocks = [block.payload for block in disk.sides[0].blocks]
    stream = encode_write_stream(blocks)
    device = FakeFdsStick()

    # Act
    stick_over(device).write_side(0, blocks)

    # Assert
    assert len(device.written) == BLANKED_PACKETS * WRITE_PAYLOAD
    assert bytes(device.written).startswith(stream)
    assert bytes(device.written)[-WRITE_PAYLOAD:] == FACTORY_FILL * FILLS_PER_PACKET


def test_a_packet_the_device_refuses_once_is_sent_again() -> None:
    # Arrange
    body = raw_side()[: 5 * WRITE_PAYLOAD]
    device = FakeFdsStick(refused_packets=(2,))

    # Act
    stick_over(device).write_raw_side(body)

    # Assert
    assert bytes(device.written) == body
    assert device.refusals == [2]


def test_a_refused_packet_is_never_skipped_past() -> None:
    # Arrange
    body = raw_side()[: 3 * WRITE_PAYLOAD]
    device = FakeFdsStick(refused_packets=(0, 1, 2))

    # Act
    stick_over(device).write_raw_side(body)

    # Assert
    assert bytes(device.written) == body


def test_a_side_read_right_after_a_write_is_tried_again_after_a_pause() -> None:
    # Arrange
    side = raw_side()[: 4 * CHUNK_PAYLOAD]
    device = FakeFdsStick(side=side, busy_reads_after_finish=1)
    pauses: list[float] = []
    stick = stick_over(device, pauses)
    stick.write_raw_side(bytes(WRITE_PAYLOAD))

    # Act
    read = stick.read_raw_side()

    # Assert
    assert read == side
    assert device.starts == [MODE_WRITE, MODE_READ, MODE_READ]
    assert pauses == [SETTLE_PAUSE_S]


def test_a_read_with_no_write_before_it_is_not_tried_again() -> None:
    # Arrange
    device = FakeFdsStick(side=raw_side(), busy_left=1)

    # Act
    with pytest.raises(HardwareFaultError, match="read error") as raised:
        stick_over(device).read_raw_side()

    # Assert
    assert raised.type is NothingReadError
    assert raised.value.kind is FaultKind.LINK
    assert device.starts == [MODE_READ]


def test_a_stick_busy_through_every_read_after_a_write_fails_the_read() -> None:
    # Arrange
    device = FakeFdsStick(side=raw_side(), busy_reads_after_finish=READS_AFTER_WRITE)
    stick = stick_over(device)
    stick.write_raw_side(bytes(WRITE_PAYLOAD))

    # Act
    with pytest.raises(HardwareFaultError, match="read error") as raised:
        stick.read_raw_side()

    # Assert
    assert raised.type is NothingReadError
    assert raised.value.kind is FaultKind.LINK
    assert device.starts == [MODE_WRITE] + [MODE_READ] * READS_AFTER_WRITE


def test_a_stick_pulled_during_a_write_is_a_link_fault() -> None:
    # Arrange
    device = FakeFdsStick(unplugged_at=2)

    # Act
    with pytest.raises(HardwareFaultError, match=UNPLUGGED) as raised:
        stick_over(device).write_raw_side(bytes(4 * WRITE_PAYLOAD))

    # Assert
    assert raised.type is HardwareFaultError
    assert raised.value.kind is FaultKind.LINK
    assert len(device.written) == 2 * WRITE_PAYLOAD


def test_a_stick_pulled_during_a_read_is_a_link_fault_and_not_read_again() -> None:
    # Arrange
    device = FakeFdsStick(side=raw_side(), unplugged_at=3)
    stick = stick_over(device)
    stick.write_raw_side(bytes(WRITE_PAYLOAD))

    # Act
    with pytest.raises(HardwareFaultError, match=UNPLUGGED) as raised:
        stick.read_raw_side()

    # Assert
    assert raised.type is HardwareFaultError
    assert raised.value.kind is FaultKind.LINK
    assert device.starts == [MODE_WRITE, MODE_READ]


def test_a_stick_settling_for_several_reads_after_a_write_is_waited_out() -> None:
    # Arrange
    side = raw_side()[: 4 * CHUNK_PAYLOAD]
    device = FakeFdsStick(side=side, busy_reads_after_finish=READS_AFTER_WRITE - 1)
    stick = stick_over(device)
    stick.write_raw_side(bytes(WRITE_PAYLOAD))

    # Act
    read = stick.read_raw_side()

    # Assert
    assert read == side
    assert device.starts == [MODE_WRITE] + [MODE_READ] * READS_AFTER_WRITE


def test_a_stale_reply_before_a_settling_stick_refuses_is_still_tried_again() -> None:
    # Arrange
    side = raw_side()[: 4 * CHUNK_PAYLOAD]
    device = FakeFdsStick(side=side, stale_first=0xFF, busy_reads_after_finish=1)
    stick = stick_over(device)
    stick.write_raw_side(bytes(WRITE_PAYLOAD))

    # Act
    read = stick.read_raw_side()

    # Assert
    assert read == side
    assert device.starts == [MODE_WRITE, MODE_READ, MODE_READ]


def test_a_write_sends_nothing_after_its_data() -> None:
    # Arrange
    device = FakeFdsStick()

    # Act
    stick_over(device).write_raw_side(bytes(WRITE_PAYLOAD))

    # Assert
    assert device.starts == [MODE_WRITE]


def test_a_side_written_then_read_back_arrives_unchanged() -> None:
    # Arrange
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    encoded = encode_block_stream([block.payload for block in disk.sides[0].blocks])
    device = FakeFdsStick()
    stick_over(device).write_raw_side(encoded)

    # Act
    device.side = bytes(device.written)[: len(encoded)]

    # Assert
    assert stick_over(device).read_raw_side() == device.side


def test_reading_a_side_through_the_driver_yields_its_blocks() -> None:
    # Arrange
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    payloads = [block.payload for block in disk.sides[0].blocks]
    device = FakeFdsStick(side=encode_block_stream(payloads))

    # Act
    read = list(stick_over(device).read_side(0))

    # Assert
    assert [block.payload for block in read] == payloads
    assert all(block.crc_ok for block in read)


def test_a_read_keeps_the_pulse_capture_it_pulled() -> None:
    # Arrange
    device = FakeFdsStick(side=raw_side()[: 2 * CHUNK_PAYLOAD])
    stick = stick_over(device)

    # Act
    list(stick.read_side(0))

    # Assert
    assert len(stick.captures) == 1


def a_full_session() -> FakeFdsStick:
    device = FakeFdsStick(side=raw_side()[:CHUNK_PAYLOAD])
    stick = stick_over(device)
    stick.read_raw_side()
    stick.write_raw_side(bytes(WRITE_PAYLOAD))
    return device


def test_a_full_session_reaches_the_device_at_all() -> None:
    # Arrange
    session = a_full_session

    # Act
    device = session()

    # Assert
    assert device.seen


def test_nothing_on_the_wire_touches_the_flash_reports() -> None:
    # Arrange
    session = a_full_session

    # Act
    device = session()

    # Assert
    assert set(device.seen).isdisjoint(FLASH_REPORTS)


def test_nothing_on_the_wire_drives_the_disk_emulator() -> None:
    # Arrange
    session = a_full_session

    # Act
    device = session()

    # Assert
    assert set(device.seen).isdisjoint(EMULATOR_REPORTS)


def test_every_side_written_ends_with_the_finish_report() -> None:
    # Arrange
    device = FakeFdsStick(side=raw_side()[:CHUNK_PAYLOAD])

    # Act
    stick_over(device).write_raw_side(bytes(WRITE_PAYLOAD))

    # Assert
    assert device.finishes == [FINISH]


def test_the_last_write_packet_is_filled_with_gap() -> None:
    # Arrange
    device = FakeFdsStick(side=raw_side()[:CHUNK_PAYLOAD])

    # Act
    stick_over(device).write_raw_side(bytes(3))

    # Assert
    assert device.written == bytes(3) + bytes([0xAA]) * (WRITE_PAYLOAD - 3)


def test_every_report_the_device_sees_is_one_the_driver_declares() -> None:
    # Arrange
    expected = {int(report) for report in ReportId}

    # Act
    result = set(a_full_session().seen)

    # Assert
    assert result <= expected


def test_closing_the_driver_closes_the_device() -> None:
    # Arrange
    device = FakeFdsStick()

    # Act
    stick_over(device).close()

    # Assert
    assert device.closed


def test_a_device_that_sends_no_data_at_all_names_the_older_firmware() -> None:
    # Arrange
    device = FakeFdsStick(side=b"")

    # Act
    with pytest.raises(HardwareFaultError) as raised:
        stick_over(device).read_raw_side()

    # Assert
    assert raised.type is HardwareFaultError
    assert "2015" in str(raised.value)
    assert raised.value.kind is FaultKind.MEDIA


def test_the_driver_records_the_report_map_the_older_firmware_used() -> None:
    # Arrange
    shared = {0x11, 0x12}

    # Act
    current = {int(report) for report in ReportId}

    # Assert
    assert LEGACY_REPORTS == (0x11, 0x12, 0x13, 0x14)
    assert set(LEGACY_REPORTS).isdisjoint(current - shared)


def formatted(game: str) -> Disk:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name=game))
    return disk


def test_a_write_through_the_driver_reads_back_as_written() -> None:
    # Arrange
    device = FakeFdsStick(side=encode_raw03(formatted("OLD"), side=0), echoes=True)
    stick = stick_over(device)

    # Act
    report = write_verified(stick, stick, formatted("NEW"), confirm=lambda _: True, backup=None)

    # Assert
    assert report.verified
    assert device.starts == [MODE_READ, MODE_WRITE, MODE_READ]


def test_a_write_reads_back_while_the_stick_settles_after_finishing() -> None:
    # Arrange
    device = FakeFdsStick(
        side=encode_raw03(formatted("OLD"), side=0), echoes=True, busy_reads_after_finish=1
    )
    stick = stick_over(device)

    # Act
    report = write_verified(stick, stick, formatted("NEW"), confirm=lambda _: True, backup=None)

    # Assert
    assert report.verified


def test_a_write_the_device_drops_is_caught_by_the_driver_readback() -> None:
    # Arrange
    device = FakeFdsStick(side=encode_raw03(formatted("OLD"), side=0))
    stick = stick_over(device)

    # Act
    with pytest.raises(WriteNotTakenError) as raised:
        write_verified(stick, stick, formatted("NEW"), confirm=lambda _: True, backup=None)

    # Assert
    assert raised.type is WriteNotTakenError
