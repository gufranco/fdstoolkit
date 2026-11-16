from __future__ import annotations

from pathlib import Path

import pytest
from device import FakeFdsStick
from fakes import seeded
from replay import ReplayDevice, ReplayDivergedError

from fdstoolkit.hardware.fdsstick import FdsStick, HidApiTransport
from fdstoolkit.hardware.recording import Event, RecordingDevice, decode_events

FAKE = seeded(__name__)
CHUNK_PAYLOAD = 0xFE
SIDE_CHUNKS = 3
STEP_MS = 1.0
REFUSED_PACKET = 40
START_READ = bytes([0x10, 0x00]).hex()
START_WRITE = bytes([0x10, 0x01]).hex()
CHUNK_ID = 0x11
CHUNK_LENGTH = 8


def no_pause(seconds: float) -> None:
    del seconds


def recorded_session(path: Path, device: FakeFdsStick) -> FdsStick:
    sink = path.open("w", encoding="utf-8")
    return FdsStick(HidApiTransport(RecordingDevice(device, sink)), pause=no_pause)


def replayed(path: Path) -> tuple[FdsStick, ReplayDevice]:
    device = ReplayDevice(decode_events(path.read_text(encoding="utf-8").splitlines()))
    return FdsStick(HidApiTransport(device), pause=no_pause), device


def test_a_recorded_read_replays_to_the_same_bytes(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "read.jsonl"
    side = FAKE.binary(length=CHUNK_PAYLOAD * SIDE_CHUNKS + 7)
    original = recorded_session(path, FakeFdsStick(side=side))
    expected = original.read_raw_side()
    original.close()
    stick, device = replayed(path)

    # Act
    result = stick.read_raw_side()

    # Assert
    stick.close()
    assert result == expected == side
    assert device.exhausted


def test_a_recorded_refusal_replays_as_a_refusal(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "write.jsonl"
    values = bytes(FAKE.random_int(1, 3) for _ in range(CHUNK_PAYLOAD * 60))
    original = recorded_session(path, FakeFdsStick(refused_packets=(REFUSED_PACKET,)))
    original.write_raw_side(values)
    original.close()
    stick, device = replayed(path)

    # Act
    stick.write_raw_side(values)

    # Assert
    stick.close()
    assert device.exhausted


def test_a_recorded_error_is_raised_again() -> None:
    # Arrange
    device = ReplayDevice([Event("send_feature_report", (START_READ,), None, "unplugged", STEP_MS)])

    # Act
    with pytest.raises(OSError, match="unplugged") as caught:
        device.send_feature_report(bytes.fromhex(START_READ))

    # Assert
    assert device.exhausted
    assert str(caught.value) == "unplugged"


def test_a_driver_that_strays_from_the_recording_is_stopped() -> None:
    # Arrange
    device = ReplayDevice([Event("send_feature_report", (START_READ,), 2, None, STEP_MS)])

    # Act
    with pytest.raises(ReplayDivergedError) as caught:
        device.send_feature_report(bytes.fromhex(START_WRITE))

    # Assert
    assert START_READ in str(caught.value)
    assert START_WRITE in str(caught.value)


def test_a_call_past_the_end_of_the_recording_is_stopped() -> None:
    # Arrange
    device = ReplayDevice([])

    # Act
    with pytest.raises(ReplayDivergedError) as caught:
        device.close()

    # Assert
    assert "after the recording ended" in str(caught.value)


def test_a_count_recorded_as_bytes_is_stopped() -> None:
    # Arrange
    device = ReplayDevice([Event("send_feature_report", (START_READ,), "00", None, STEP_MS)])

    # Act
    with pytest.raises(ReplayDivergedError) as caught:
        device.send_feature_report(bytes.fromhex(START_READ))

    # Assert
    assert "is not a number" in str(caught.value)


def test_bytes_recorded_as_a_count_are_stopped() -> None:
    # Arrange
    device = ReplayDevice([Event("get_feature_report", (CHUNK_ID, CHUNK_LENGTH), 1, None, STEP_MS)])

    # Act
    with pytest.raises(ReplayDivergedError) as caught:
        device.get_feature_report(CHUNK_ID, CHUNK_LENGTH)

    # Assert
    assert "is not bytes" in str(caught.value)
