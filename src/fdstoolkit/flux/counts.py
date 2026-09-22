from __future__ import annotations

from typing import Final

from fdstoolkit.codecs.raw import unpack_raw03
from fdstoolkit.flux.model import (
    LONG_NS,
    MEDIUM_NS,
    NS_PER_SECOND,
    SHORT_NS,
    FluxCapture,
    FluxTrack,
    Revolution,
    Source,
)

CAPTURE_CLOCK_HZ: Final = 6_000_000
TICK_NS: Final = NS_PER_SECOND / CAPTURE_CLOCK_HZ
MAX_COUNT: Final = 0xFF
CLASS_NS: Final = (SHORT_NS, MEDIUM_NS, LONG_NS, LONG_NS)


def counts_to_ns(count: int) -> int:
    return round(count * TICK_NS)


def _capture(intervals: tuple[int, ...], track: int) -> FluxCapture:
    if not intervals:
        message = "the capture carries no pulse"
        raise ValueError(message)
    return FluxCapture(
        source=Source.FDSSTICK,
        tracks=(FluxTrack(index=track, revolutions=(Revolution(intervals=intervals),)),),
        sample_ns=TICK_NS,
    )


def read_counts(data: bytes, *, track: int = 0) -> FluxCapture:
    return _capture(tuple(counts_to_ns(count) for count in data), track)


def read_raw03(data: bytes, *, track: int = 0) -> FluxCapture:
    return _capture(tuple(CLASS_NS[value] for value in unpack_raw03(data)), track)


def write_counts(capture: FluxCapture) -> bytes:
    return bytes(
        min(MAX_COUNT, max(1, round(interval / TICK_NS)))
        for track in capture.tracks
        for interval in track.intervals()
    )
