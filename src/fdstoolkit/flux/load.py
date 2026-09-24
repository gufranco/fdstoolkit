from __future__ import annotations

from enum import StrEnum

from fdstoolkit.flux.counts import read_counts, read_raw03
from fdstoolkit.flux.model import FluxCapture


class CaptureFormat(StrEnum):
    COUNTS = "counts"
    RAW03 = "raw03"


def detect_format(data: bytes) -> CaptureFormat:
    if not data:
        message = "the capture file is empty"
        raise ValueError(message)
    return CaptureFormat.COUNTS


def load_capture(
    data: bytes,
    *,
    fmt: CaptureFormat | None = None,
    track: int = 0,
) -> FluxCapture:
    chosen = fmt or detect_format(data)
    if chosen is CaptureFormat.RAW03:
        return read_raw03(data, track=track)
    return read_counts(data, track=track)
