from __future__ import annotations

import pytest

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.flux.counts import write_counts
from fdstoolkit.flux.hfe import write_hfe
from fdstoolkit.flux.kryoflux import OOB, OOB_EOF
from fdstoolkit.flux.load import CaptureFormat, detect_format, load_capture
from fdstoolkit.flux.model import Source
from fdstoolkit.flux.scp import write_scp
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


EOF_BLOCK = bytes((OOB, OOB_EOF)) + (0x0D0D).to_bytes(2, "little")


def test_a_supercard_pro_capture_is_detected() -> None:
    data = write_scp(synthesise(_disk()))

    assert detect_format(data) is CaptureFormat.SCP
    assert load_capture(data).source is Source.SCP


def test_an_hxc_image_is_detected() -> None:
    data = write_hfe(synthesise(_disk()), bit_rate_kbps=250)

    assert detect_format(data) is CaptureFormat.HFE
    assert load_capture(data).source is Source.HFE


def test_a_kryoflux_stream_is_detected() -> None:
    info = bytes((OOB, 0x04)) + (11).to_bytes(2, "little") + b"name=value\0"
    data = info + bytes((0x40, 0x50)) + EOF_BLOCK

    assert detect_format(data) is CaptureFormat.KRYOFLUX
    assert load_capture(data).source is Source.KRYOFLUX


def test_a_counts_capture_is_the_fallback() -> None:
    data = write_counts(synthesise(_disk()))

    assert detect_format(data) is CaptureFormat.COUNTS
    assert load_capture(data).source is Source.FDSSTICK


def test_a_packed_capture_is_named_rather_than_guessed() -> None:
    capture = load_capture(b"\x1b" * 64, fmt=CaptureFormat.RAW03)

    assert capture.source is Source.FDSSTICK


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(ValueError, match="empty"):
        detect_format(b"")


def test_loading_an_empty_file_is_refused() -> None:
    with pytest.raises(ValueError, match="empty"):
        load_capture(b"")
