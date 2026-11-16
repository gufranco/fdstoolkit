from __future__ import annotations

import pytest
from device import ID_DISK_START, ID_FINISH_WRITE, UNPLUGGED, FakeFdsStick
from fakes import game_name, seeded
from protocol_kit import (
    EMULATOR_REPORTS,
    FINISH,
    FLASH_REPORTS,
    a_full_session,
    formatted,
    raw_side,
    stick_over,
)

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.raw import encode_block_stream, encode_raw03
from fdstoolkit.hardware.fdsstick import (
    CHUNK_PAYLOAD,
    LEGACY_REPORTS,
    MODE_READ,
    MODE_WRITE,
    READS_AFTER_WRITE,
    SETTLE_PAUSE_S,
    WRITE_PAYLOAD,
    WRITE_STARTS,
    DriveNotReadyError,
    HidApiTransport,
    NothingReadError,
    ReportId,
)
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError
from fdstoolkit.hardware.session import WriteNotTakenError
from fdstoolkit.hardware.writing import write_verified

FAKE = seeded(__name__)
GAME = game_name(FAKE)
OTHER_GAME = game_name(FAKE)


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
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name=OTHER_GAME))
    encoded = encode_block_stream([block.payload for block in disk.sides[0].blocks])
    device = FakeFdsStick()
    stick_over(device).write_raw_side(encoded)
    device.side = bytes(device.written)[: len(encoded)]

    # Act
    read = stick_over(device).read_raw_side()

    # Assert
    assert read == device.side


def test_reading_a_side_through_the_driver_yields_its_blocks() -> None:
    # Arrange
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name=OTHER_GAME))
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


def test_a_write_through_the_driver_reads_back_as_written() -> None:
    # Arrange
    device = FakeFdsStick(side=encode_raw03(formatted(GAME), side=0), echoes=True)
    stick = stick_over(device)

    # Act
    report = write_verified(stick, stick, formatted("NEW"), confirm=lambda _: True, backup=None)

    # Assert
    assert report.verified
    assert device.starts == [MODE_READ, MODE_WRITE, MODE_READ]


def test_a_write_reads_back_while_the_stick_settles_after_finishing() -> None:
    # Arrange
    device = FakeFdsStick(
        side=encode_raw03(formatted(GAME), side=0), echoes=True, busy_reads_after_finish=1
    )
    stick = stick_over(device)

    # Act
    report = write_verified(stick, stick, formatted("NEW"), confirm=lambda _: True, backup=None)

    # Assert
    assert report.verified


def test_a_write_the_device_drops_is_caught_by_the_driver_readback() -> None:
    # Arrange
    device = FakeFdsStick(side=encode_raw03(formatted(GAME), side=0))
    stick = stick_over(device)

    # Act
    with pytest.raises(WriteNotTakenError) as raised:
        write_verified(stick, stick, formatted("NEW"), confirm=lambda _: True, backup=None)

    # Assert
    assert raised.type is WriteNotTakenError


def test_a_feature_report_the_device_refuses_raises_rather_than_passing() -> None:
    # Arrange
    transport = HidApiTransport(FakeFdsStick(refused_features=frozenset({ID_FINISH_WRITE})))

    # Act
    with pytest.raises(OSError, match="refused report 0x20") as raised:
        transport.send_feature(FINISH)

    # Assert
    assert raised.type is OSError


def test_a_read_whose_start_is_refused_is_a_link_fault() -> None:
    # Arrange
    device = FakeFdsStick(side=raw_side(), refused_features=frozenset({ID_DISK_START}))

    # Act
    with pytest.raises(HardwareFaultError) as raised:
        stick_over(device).read_raw_side()

    # Assert
    assert raised.type is NothingReadError
    assert raised.value.kind is FaultKind.LINK


def test_a_write_whose_start_is_refused_is_started_again_then_a_link_fault() -> None:
    # Arrange
    device = FakeFdsStick(refused_features=frozenset({ID_DISK_START}))
    pauses: list[float] = []

    # Act
    with pytest.raises(HardwareFaultError) as raised:
        stick_over(device, pauses).write_raw_side(bytes(WRITE_PAYLOAD * 30))

    # Assert
    assert raised.type is DriveNotReadyError
    assert pauses == [SETTLE_PAUSE_S] * (WRITE_STARTS - 1)


def test_a_write_whose_finish_is_refused_is_a_link_fault() -> None:
    # Arrange
    device = FakeFdsStick(refused_features=frozenset({ID_FINISH_WRITE}))

    # Act
    with pytest.raises(HardwareFaultError, match="failed to finish the write") as raised:
        stick_over(device).write_raw_side(bytes(WRITE_PAYLOAD * 30))

    # Assert
    assert raised.value.kind is FaultKind.LINK
    assert device.finishes == []
