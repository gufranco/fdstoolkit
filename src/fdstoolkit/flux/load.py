from __future__ import annotations

from enum import StrEnum

from fdstoolkit.flux.counts import read_counts, read_raw03
from fdstoolkit.flux.hfe import is_hfe, read_hfe
from fdstoolkit.flux.kryoflux import is_kryoflux, read_stream
from fdstoolkit.flux.model import FluxCapture
from fdstoolkit.flux.scp import is_scp, read_scp


class CaptureFormat(StrEnum):
    SCP = "scp"
    HFE = "hfe"
    KRYOFLUX = "kryoflux"
    COUNTS = "counts"
    RAW03 = "raw03"


def detect_format(data: bytes) -> CaptureFormat:
    if not data:
        message = "the capture file is empty"
        raise ValueError(message)
    if is_scp(data):
        return CaptureFormat.SCP
    if is_hfe(data):
        return CaptureFormat.HFE
    if is_kryoflux(data):
        return CaptureFormat.KRYOFLUX
    return CaptureFormat.COUNTS


def load_capture(
    data: bytes,
    *,
    fmt: CaptureFormat | None = None,
    track: int = 0,
) -> FluxCapture:
    chosen = fmt or detect_format(data)
    if chosen is CaptureFormat.SCP:
        return read_scp(data)
    if chosen is CaptureFormat.HFE:
        return read_hfe(data)
    if chosen is CaptureFormat.KRYOFLUX:
        return read_stream(data, track=track)
    if chosen is CaptureFormat.RAW03:
        return read_raw03(data, track=track)
    return read_counts(data, track=track)
