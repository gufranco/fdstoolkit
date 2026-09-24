from __future__ import annotations

import pytest

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.flux.counts import write_counts
from fdstoolkit.flux.load import CaptureFormat, detect_format, load_capture
from fdstoolkit.flux.model import Source
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


def test_a_capture_is_read_as_counts_unless_named_otherwise() -> None:
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
