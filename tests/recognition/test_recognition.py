from __future__ import annotations

from pathlib import Path
from typing import Final

from capture_fixture import disk_with_a_file

from fdstoolkit.codecs.raw import block_regions, encode_block_stream, pack_raw03, unpack_raw03
from fdstoolkit.drive.captures import Capture
from fdstoolkit.drive.recognition import rate_lines, read_rate, read_rates
from fdstoolkit.drive.sampling import CountedSpan

FIXTURE: Final = Path("tests/fixtures/fdsstick/calibration-side.raw03")
FIXTURE_COUNTED: Final = 270131
TRAILING_GAP: Final = 4000
SPLICE_SKIPPED: Final = 144
INVALID: Final = 3
STRAYS: Final = 3
NOISE: Final = 1000


def _one_block_read(strays: int) -> bytes:
    disk = disk_with_a_file()
    values = unpack_raw03(encode_block_stream([disk.sides[0].blocks[0].payload]))
    tail = bytes([INVALID]) * strays + bytes(TRAILING_GAP - strays)
    return values + tail


def test_the_real_calibration_read_fits_every_counted_pulse_to_a_class() -> None:
    # Arrange
    capture = Capture(side=0, read=1, data=FIXTURE.read_bytes())

    # Act
    rate = read_rate(capture)

    # Assert
    assert rate.recognition.counted == FIXTURE_COUNTED
    assert rate.recognition.unclassed == 0
    assert rate.recognition.rate == 1.0
    assert rate.recognition.span is CountedSpan.DECLARED


def test_a_read_with_no_file_amount_is_counted_to_its_end() -> None:
    # Arrange
    values = _one_block_read(STRAYS)
    start, _ = block_regions(values)[0]
    counted = len(values) - start - SPLICE_SKIPPED

    # Act
    rate = read_rate(Capture(side=0, read=1, data=pack_raw03(values)))

    # Assert
    assert rate.recognition.span is CountedSpan.TO_END
    assert rate.recognition.counted == counted
    assert rate.recognition.unclassed == STRAYS
    assert rate.recognition.rate == (counted - STRAYS) / counted


def test_a_read_where_no_block_frames_is_counted_whole() -> None:
    # Arrange
    values = bytes([INVALID]) * NOISE + bytes(NOISE)

    # Act
    rate = read_rate(Capture(side=1, read=2, data=pack_raw03(values)))

    # Assert
    assert rate.recognition.span is CountedSpan.WHOLE
    assert rate.recognition.counted == 2 * NOISE
    assert rate.recognition.rate == 0.5
    assert rate.render() == (
        "side 1 read 2: 50.00% of 2000 pulses fit a class, counted over the whole read, "
        "since no block framed"
    )


def test_an_empty_read_says_no_pulse_was_read() -> None:
    # Arrange
    capture = Capture(side=0, read=3, data=b"")

    # Act
    rate = read_rate(capture)

    # Assert
    assert rate.recognition.rate == 0.0
    assert rate.render() == "side 0 read 3: no pulse was read"


def test_every_capture_gets_its_own_line_in_order() -> None:
    # Arrange
    captures = (
        Capture(side=0, read=1, data=FIXTURE.read_bytes()),
        Capture(side=0, read=2, data=b""),
    )

    # Act
    lines = rate_lines(captures)

    # Assert
    assert lines == (
        (
            "side 0 read 1: 100.00% of 270131 pulses fit a class, counted from the first block "
            "to the end of the last declared one"
        ),
        "side 0 read 2: no pulse was read",
    )
    assert [rate.read for rate in read_rates(captures)] == [1, 2]
