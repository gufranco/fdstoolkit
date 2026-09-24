from __future__ import annotations

import pytest
from device import FakeFdsStick

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.raw import encode_block_stream
from fdstoolkit.hardware.fdsstick import (
    CHUNK_PAYLOAD,
    LEGACY_REPORTS,
    MODE_READ,
    MODE_WRITE,
    PRODUCT_ID,
    RAW_SIDE_LIMIT,
    SETTLED_PACKETS,
    VENDOR_ID,
    WRITE_PAYLOAD,
    FdsStick,
    HidApiTransport,
    ReportId,
)
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError

FLASH_REPORTS = frozenset({0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09})
EMULATOR_REPORTS = frozenset({0x20, 0x21, 0x22, 0x23})
WRITE_REPORT_LENGTH = 0x100
PACKETS_PAST_THE_WRAP = 300


def raw_side(packets: int = PACKETS_PAST_THE_WRAP) -> bytes:
    return bytes(range(256)) * (packets * CHUNK_PAYLOAD // 256 + 1)


def stick_over(device: FakeFdsStick) -> FdsStick:
    return FdsStick(HidApiTransport(device))


def test_the_device_is_the_one_both_reference_tools_open() -> None:
    assert (VENDOR_ID, PRODUCT_ID) == (0x16D0, 0x0AAA)


def test_the_driver_knows_only_the_reports_that_reach_a_real_drive() -> None:
    assert {int(report) for report in ReportId} == {0x10, 0x11, 0x12}


def test_a_whole_side_comes_back_byte_for_byte() -> None:
    side = raw_side()[: 12 * CHUNK_PAYLOAD]
    device = FakeFdsStick(side=side)

    assert stick_over(device).read_raw_side() == side


def test_a_side_long_enough_to_wrap_the_counter_still_comes_back_whole() -> None:
    side = raw_side()
    device = FakeFdsStick(side=side)

    read = stick_over(device).read_raw_side()

    assert device.served > 0xFF
    assert read == side


def test_a_read_that_wraps_reports_no_lost_data() -> None:
    device = FakeFdsStick(side=raw_side())

    stick = stick_over(device)
    stick.read_raw_side()

    assert stick.resyncs == ()


def test_a_stale_first_reply_is_dropped_rather_than_stored() -> None:
    side = raw_side()[: 4 * CHUNK_PAYLOAD]
    device = FakeFdsStick(side=side, stale_first=0x7A)

    assert stick_over(device).read_raw_side() == side


def test_a_stale_first_reply_resyncs_the_counter_once() -> None:
    device = FakeFdsStick(side=raw_side()[: 4 * CHUNK_PAYLOAD], stale_first=0x7A)

    stick = stick_over(device)
    stick.read_raw_side()

    assert stick.resyncs == ((0x7B, 1),)


def test_a_dropped_packet_does_not_abandon_the_dump() -> None:
    side = raw_side()[: 8 * CHUNK_PAYLOAD]
    device = FakeFdsStick(side=side, drop_after=3)

    assert stick_over(device).read_raw_side() == side


def test_a_dropped_packet_is_recorded_so_the_read_can_be_judged() -> None:
    device = FakeFdsStick(side=raw_side()[: 8 * CHUNK_PAYLOAD], drop_after=3)

    stick = stick_over(device)
    stick.read_raw_side()

    assert stick.resyncs == ((5, 6),)


def test_a_side_that_ends_mid_chunk_keeps_its_last_bytes() -> None:
    side = raw_side()[: 3 * CHUNK_PAYLOAD + 17]
    device = FakeFdsStick(side=side)

    assert stick_over(device).read_raw_side() == side


def test_a_device_that_pads_the_last_chunk_still_ends_the_side() -> None:
    side = raw_side()[: 3 * CHUNK_PAYLOAD]
    device = FakeFdsStick(side=side, pads_last_chunk=True)

    assert stick_over(device).read_raw_side() == side


def test_a_reply_too_short_to_carry_a_sequence_is_a_link_fault() -> None:
    device = FakeFdsStick(side=raw_side(), short_reply=True)

    with pytest.raises(HardwareFaultError) as raised:
        stick_over(device).read_raw_side()

    assert raised.value.kind is FaultKind.LINK


def test_a_disk_that_never_ends_stops_at_the_raw_ceiling() -> None:
    device = FakeFdsStick(side=bytes(RAW_SIDE_LIMIT * 2))

    assert len(stick_over(device).read_raw_side()) >= RAW_SIDE_LIMIT


def test_a_read_arms_the_device_in_read_mode() -> None:
    device = FakeFdsStick(side=raw_side()[:CHUNK_PAYLOAD])

    stick_over(device).read_raw_side()

    assert device.starts == [MODE_READ]


def test_a_write_arms_the_device_in_write_mode() -> None:
    device = FakeFdsStick()

    stick_over(device).write_raw_side(bytes(WRITE_PAYLOAD))

    assert device.starts == [MODE_WRITE]


def test_everything_handed_to_a_write_reaches_the_device() -> None:
    body = raw_side()[: 5 * WRITE_PAYLOAD]
    device = FakeFdsStick()

    stick_over(device).write_raw_side(body)

    assert bytes(device.written) == body


def test_a_short_final_write_is_padded_to_a_whole_report() -> None:
    device = FakeFdsStick()

    stick_over(device).write_raw_side(bytes(10))

    assert len(device.written) == WRITE_PAYLOAD


def test_a_device_that_stops_early_is_a_link_fault() -> None:
    device = FakeFdsStick(accepts_writes=3)

    with pytest.raises(HardwareFaultError) as raised:
        stick_over(device).write_raw_side(bytes(WRITE_PAYLOAD * 10))

    assert raised.value.kind is FaultKind.LINK


def test_a_device_that_stops_once_the_disk_has_turned_is_not_a_fault() -> None:
    device = FakeFdsStick(accepts_writes=SETTLED_PACKETS)

    stick_over(device).write_raw_side(bytes(WRITE_PAYLOAD * (SETTLED_PACKETS + 5)))

    assert len(device.written) == SETTLED_PACKETS * WRITE_PAYLOAD


def test_a_write_sends_nothing_after_its_data() -> None:
    device = FakeFdsStick()

    stick_over(device).write_raw_side(bytes(WRITE_PAYLOAD))

    assert device.starts == [MODE_WRITE]


def test_a_side_written_then_read_back_arrives_unchanged() -> None:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    encoded = encode_block_stream([block.payload for block in disk.sides[0].blocks])
    device = FakeFdsStick()

    stick_over(device).write_raw_side(encoded)
    device.side = bytes(device.written)[: len(encoded)]

    assert stick_over(device).read_raw_side() == device.side


def test_reading_a_side_through_the_driver_yields_its_blocks() -> None:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    payloads = [block.payload for block in disk.sides[0].blocks]
    device = FakeFdsStick(side=encode_block_stream(payloads))

    read = list(stick_over(device).read_side(0))

    assert [block.payload for block in read] == payloads
    assert all(block.crc_ok for block in read)


def test_a_read_keeps_the_pulse_capture_it_pulled() -> None:
    device = FakeFdsStick(side=raw_side()[: 2 * CHUNK_PAYLOAD])

    stick = stick_over(device)
    list(stick.read_side(0))

    assert len(stick.captures) == 1


def a_full_session() -> FakeFdsStick:
    device = FakeFdsStick(side=raw_side()[:CHUNK_PAYLOAD])
    stick = stick_over(device)
    stick.read_raw_side()
    stick.write_raw_side(bytes(WRITE_PAYLOAD))
    return device


def test_a_full_session_reaches_the_device_at_all() -> None:
    assert a_full_session().seen


def test_nothing_on_the_wire_touches_the_flash_reports() -> None:
    assert set(a_full_session().seen).isdisjoint(FLASH_REPORTS)


def test_nothing_on_the_wire_drives_the_disk_emulator() -> None:
    assert set(a_full_session().seen).isdisjoint(EMULATOR_REPORTS)


def test_every_report_the_device_sees_is_one_the_driver_declares() -> None:
    assert set(a_full_session().seen) <= {int(report) for report in ReportId}


def test_closing_the_driver_closes_the_device() -> None:
    device = FakeFdsStick()

    stick_over(device).close()

    assert device.closed


def test_a_device_that_sends_no_data_at_all_names_the_older_firmware() -> None:
    device = FakeFdsStick(side=b"")

    with pytest.raises(HardwareFaultError) as raised:
        stick_over(device).read_raw_side()

    assert "2015" in str(raised.value)
    assert raised.value.kind is FaultKind.MEDIA


def test_the_driver_records_the_report_map_the_older_firmware_used() -> None:
    assert LEGACY_REPORTS == (0x11, 0x12, 0x13, 0x14)
    assert set(LEGACY_REPORTS).isdisjoint({int(report) for report in ReportId} - {0x11, 0x12})
