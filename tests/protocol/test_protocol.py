from __future__ import annotations

import pytest
from device import ID_FINISH_WRITE, FakeFdsStick
from protocol_kit import FACTORY_FILL, FILLS_PER_PACKET, raw_side, stick_over

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.write_stream import encode_write_stream
from fdstoolkit.hardware.fdsstick import (
    BLANKED_PACKETS,
    CHUNK_PAYLOAD,
    LEAD_IN_PACKETS,
    MODE_READ,
    MODE_WRITE,
    PRODUCT_ID,
    RAW_SIDE_LIMIT,
    SETTLE_PAUSE_S,
    VENDOR_ID,
    WRITE_PAYLOAD,
    WRITE_STARTS,
    DriveNotReadyError,
    ReportId,
)
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError


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
