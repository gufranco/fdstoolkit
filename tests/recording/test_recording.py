from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from device import FakeFdsStick
from fakes import seeded
from fdsstick_kit import FakeHidDevice

from fdstoolkit.hardware.fdsstick import PRODUCT_ID, VENDOR_ID, open_fdsstick
from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.hardware.recording import (
    RECORD_ENV,
    RECORDING_FORMAT,
    RECORDING_VERSION,
    Event,
    RecordingDevice,
    RecordingError,
    decode_events,
    encode_event,
    recorded,
    session_path,
)

FAKE = seeded(__name__)
STEP_S = 0.25
STEP_MS = 250.0
START = bytes([0x10, 0x00])
CHUNK_ID = 0x11
CHUNK_LENGTH = 257
UNKNOWN_REPORT = 0x05
HEADER = json.dumps({"format": RECORDING_FORMAT, "version": RECORDING_VERSION})


class TickingClock:
    def __init__(self, step_s: float) -> None:
        self._now = 0.0
        self._step = step_s

    def __call__(self) -> float:
        now = self._now
        self._now += self._step
        return now


class RefusingOpen(FakeFdsStick):
    def open(self, vendor_id: int, product_id: int) -> None:
        del vendor_id, product_id
        message = "no such device"
        raise OSError(message)


def recorder(path: Path, device: FakeFdsStick) -> RecordingDevice:
    return RecordingDevice(device, path.open("w", encoding="utf-8"), clock=TickingClock(STEP_S))


def events_in(path: Path) -> tuple[Event, ...]:
    return decode_events(path.read_text(encoding="utf-8").splitlines())


def side_bytes() -> bytes:
    return FAKE.binary(length=CHUNK_LENGTH * 2)


def test_every_call_is_recorded_with_its_answer(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "session.jsonl"
    device = recorder(path, FakeFdsStick(side=side_bytes()))
    device.open(VENDOR_ID, PRODUCT_ID)
    device.send_feature_report(START)
    answer = device.get_feature_report(CHUNK_ID, CHUNK_LENGTH)
    device.close()

    # Act
    events = events_in(path)

    # Assert
    assert [event.call for event in events] == [
        "open",
        "send_feature_report",
        "get_feature_report",
        "close",
    ]
    assert events[0].args == (VENDOR_ID, PRODUCT_ID)
    assert events[1].args == (START.hex(),)
    assert events[1].result == len(START)
    assert events[2].result == bytes(answer).hex()
    assert {event.elapsed_ms for event in events} == {STEP_MS}


def test_a_write_is_recorded_with_what_the_device_took(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "session.jsonl"
    packet = bytes([0x12]) + FAKE.binary(length=16)
    device = recorder(path, FakeFdsStick())

    # Act
    taken = device.write(packet)

    # Assert
    device.close()
    assert events_in(path)[0] == Event("write", (packet.hex(),), taken, None, STEP_MS)


def test_a_refused_feature_report_keeps_its_answer(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "session.jsonl"
    device = recorder(path, FakeFdsStick(refused_features=frozenset({START[0]})))

    # Act
    answer = device.send_feature_report(START)

    # Assert
    device.close()
    assert answer == -1
    assert events_in(path)[0].result == -1


def test_a_call_that_raises_is_recorded_and_raised_again(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "session.jsonl"
    device = recorder(path, FakeFdsStick())

    # Act
    with pytest.raises(OSError, match="asked for report") as caught:
        device.get_feature_report(UNKNOWN_REPORT, CHUNK_LENGTH)

    # Assert
    device.close()
    event = events_in(path)[0]
    assert event.error == str(caught.value)
    assert event.result is None


def test_a_failed_open_closes_the_recording(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "session.jsonl"
    sink = path.open("w", encoding="utf-8")
    device = RecordingDevice(RefusingOpen(), sink, clock=TickingClock(STEP_S))

    # Act
    with pytest.raises(OSError, match="no such device"):
        device.open(VENDOR_ID, PRODUCT_ID)

    # Assert
    assert sink.closed
    assert events_in(path)[0].error == "no such device"


def test_a_closed_recording_ignores_later_calls(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "session.jsonl"
    device = RecordingDevice(
        RefusingOpen(), path.open("w", encoding="utf-8"), clock=TickingClock(STEP_S)
    )
    with pytest.raises(OSError, match="no such device"):
        device.open(VENDOR_ID, PRODUCT_ID)

    # Act
    device.close()

    # Assert
    assert [event.call for event in events_in(path)] == ["open"]


def test_an_event_survives_encoding_and_decoding() -> None:
    # Arrange
    event = Event("write", (FAKE.binary(length=8).hex(),), None, "refused", STEP_MS)

    # Act
    decoded = decode_events([HEADER, encode_event(event)])

    # Assert
    assert decoded == (event,)


@pytest.mark.parametrize(
    ("lines", "reason"),
    [
        ([], "empty"),
        (["not json"], "does not start with"),
        ([json.dumps({"format": RECORDING_FORMAT, "version": 0})], "this version reads"),
        ([HEADER, "not json"], "line 2 of the recording is not an event"),
        ([HEADER, json.dumps({"call": "open"})], "line 2 of the recording is not an event"),
        (
            [
                HEADER,
                json.dumps(
                    {"call": "open", "args": [True], "result": None, "error": None, "ms": 1}
                ),
            ],
            "neither a number nor text",
        ),
        (
            [
                HEADER,
                json.dumps({"call": "open", "args": [], "result": [1], "error": None, "ms": 1}),
            ],
            "neither a number nor text",
        ),
        (
            [HEADER, json.dumps({"call": 7, "args": [], "result": None, "error": None, "ms": 1})],
            "no call name",
        ),
        (
            [
                HEADER,
                json.dumps({"call": "open", "args": "ab", "result": None, "error": None, "ms": 1}),
            ],
            "no argument list",
        ),
        (
            [HEADER, json.dumps({"call": "open", "args": [], "result": None, "error": 3, "ms": 1})],
            "error that is not text",
        ),
    ],
)
def test_a_damaged_recording_is_refused_with_the_reason(lines: list[str], reason: str) -> None:
    # Arrange
    expected = reason

    # Act
    with pytest.raises(RecordingError) as caught:
        decode_events(lines)

    # Assert
    assert expected in str(caught.value)


def test_blank_lines_in_a_recording_are_skipped() -> None:
    # Arrange
    event = Event("close", (), None, None, STEP_MS)

    # Act
    decoded = decode_events([HEADER, "", encode_event(event), "  "])

    # Assert
    assert decoded == (event,)


def test_without_the_setting_the_device_is_not_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.delenv(RECORD_ENV, raising=False)
    device = FakeFdsStick()

    # Act
    result = recorded(device)

    # Assert
    assert result is device


def test_the_setting_names_a_folder_that_gets_one_file_per_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    folder = tmp_path / FAKE.word() / FAKE.word()
    monkeypatch.setenv(RECORD_ENV, str(folder))

    # Act
    device = recorded(FakeFdsStick())

    # Assert
    assert isinstance(device, RecordingDevice)
    device.close()
    sessions = list(folder.glob("session-*.jsonl"))
    assert len(sessions) == 1
    assert [event.call for event in events_in(sessions[0])] == ["close"]


def test_a_session_file_is_named_by_the_time_it_started(tmp_path: Path) -> None:
    # Arrange
    folder = tmp_path

    # Act
    path = session_path(folder)

    # Assert
    assert path.parent == folder
    assert path.name.startswith("session-")
    assert path.suffix == ".jsonl"


def test_opening_the_stick_records_the_session_when_asked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    device = FakeHidDevice()

    class FakeModule:
        def device(self) -> FakeHidDevice:
            return device

    monkeypatch.setitem(sys.modules, "hid", FakeModule())
    monkeypatch.setenv(RECORD_ENV, str(tmp_path))
    stick = open_fdsstick()

    # Act
    stick.close()

    # Assert
    (session,) = tmp_path.glob("session-*.jsonl")
    calls = [(event.call, event.args) for event in events_in(session)]
    assert calls == [("open", (VENDOR_ID, PRODUCT_ID)), ("close", ())]


def test_a_folder_that_cannot_hold_a_recording_stops_the_opening(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    blocker = tmp_path / FAKE.word()
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setenv(RECORD_ENV, str(blocker / FAKE.word()))

    # Act
    with pytest.raises(HardwareFaultError) as caught:
        recorded(FakeFdsStick())

    # Assert
    assert RECORD_ENV in str(caught.value)
    assert "cannot hold a recording" in str(caught.value)


def test_a_damaged_line_is_named_by_its_place_in_the_file() -> None:
    # Arrange
    lines = [HEADER, "", "not json"]

    # Act
    with pytest.raises(RecordingError) as caught:
        decode_events(lines)

    # Assert
    assert "line 3 " in str(caught.value)
