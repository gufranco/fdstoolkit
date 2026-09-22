from __future__ import annotations

import struct

import pytest

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.flux.model import FluxCapture, Source
from fdstoolkit.flux.scp import (
    HEADER_SIZE,
    MAGIC,
    RESOLUTION_NS,
    is_scp,
    read_scp,
    write_scp,
)
from fdstoolkit.flux.synth import synthesise


def _disk() -> Disk:
    payload = bytes([BlockKind.DISK_INFO]) + b"*NINTENDO-HVC*" + bytes(41)
    return Disk(
        sides=(
            Side(
                blocks=(Block(kind=BlockKind.DISK_INFO, payload=payload),),
                tail=b"",
                capacity=65500,
            ),
        )
    )


def _capture() -> FluxCapture:
    return synthesise(_disk())


def test_a_written_capture_is_recognised() -> None:
    assert is_scp(write_scp(_capture()))


def test_other_bytes_are_not_a_capture() -> None:
    assert not is_scp(b"HXCPICFE" + bytes(32))
    assert not is_scp(b"")


def test_a_capture_round_trips_through_the_format() -> None:
    capture = _capture()

    restored = read_scp(write_scp(capture))

    assert restored.source is Source.SCP
    assert restored.track_count == capture.track_count
    assert restored.track(0).revolution_count == 1


def test_the_intervals_survive_the_round_trip_within_one_tick() -> None:
    capture = _capture()

    restored = read_scp(write_scp(capture))

    original = capture.track(0).intervals()
    recovered = restored.track(0).intervals()
    assert len(recovered) == len(original)
    assert all(abs(a - b) <= RESOLUTION_NS for a, b in zip(original, recovered, strict=True))


def test_several_revolutions_survive_the_round_trip() -> None:
    capture = synthesise(_disk(), revolutions=3)

    restored = read_scp(write_scp(capture))

    assert restored.track(0).revolution_count == 3


def test_a_file_that_is_too_short_is_refused() -> None:
    with pytest.raises(ValueError, match="too short"):
        read_scp(b"SCP")


def test_a_file_without_the_signature_is_refused() -> None:
    with pytest.raises(ValueError, match="not a SuperCard Pro capture"):
        read_scp(b"BAD" + bytes(HEADER_SIZE))


def test_a_capture_with_no_track_entry_is_refused() -> None:
    header = bytearray(write_scp(_capture())[:HEADER_SIZE])
    header[0x06] = 0
    header[0x07] = 0
    with pytest.raises(ValueError, match="no track"):
        read_scp(bytes(header) + bytes(4 * 168))


def test_a_track_whose_offset_runs_past_the_file_is_refused() -> None:
    data = bytearray(write_scp(_capture()))
    struct.pack_into("<I", data, HEADER_SIZE, len(data) + 4096)
    with pytest.raises(ValueError, match="points past the end"):
        read_scp(bytes(data))


def test_a_track_without_its_signature_is_refused() -> None:
    data = bytearray(write_scp(_capture()))
    offset = struct.unpack_from("<I", data, HEADER_SIZE)[0]
    data[offset : offset + 3] = b"BAD"
    with pytest.raises(ValueError, match="does not start with"):
        read_scp(bytes(data))


def test_the_magic_is_the_three_byte_signature() -> None:
    assert MAGIC == b"SCP"
