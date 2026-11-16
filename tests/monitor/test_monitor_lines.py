from __future__ import annotations

from monitor_kit import Reader, nudged, reference_side, stream

from fdstoolkit.codecs.raw import (
    encode_block_stream,
    pack_raw03,
)
from fdstoolkit.core.bios import REPAIR_HINTS
from fdstoolkit.drive.monitor import (
    Mode,
    Trend,
    calibrate,
    describe,
)
from fdstoolkit.drive.sampling import (
    SideSample,
    SpeedReading,
    sample,
)


def test_misread_pulses_that_lean_neither_way_are_not_speed() -> None:
    # Arrange
    blocks = (True, False)
    short = 10
    long = 10
    invalid = 0
    compared = 100
    referenced = True

    # Act
    found = SideSample(
        blocks=blocks,
        short=short,
        long=long,
        invalid=invalid,
        compared=compared,
        referenced=referenced,
    )

    # Assert
    assert found.speed is SpeedReading.ERRORS


def test_a_line_names_blocks_missed_apart_one_by_one() -> None:
    # Arrange
    found = SideSample(
        blocks=(True, False, True, False), short=0, long=0, invalid=0, compared=0, referenced=False
    )

    # Act
    line = describe(Mode.HEAD, 1, found, Trend.FIRST)

    # Assert
    assert "blocks 1, 3 not read" in line


def test_a_calibration_needs_no_progress_callback() -> None:
    # Arrange
    side = reference_side()

    # Act
    result = calibrate(Reader([stream(side)]), mode=Mode.HEAD, reads=1, reference=side)

    # Assert
    assert result.clean


def test_a_line_names_a_single_missed_block() -> None:
    # Arrange
    blocks = (True, False, True)
    short = 0
    long = 0
    invalid = 0
    compared = 0
    referenced = False

    # Act
    found = SideSample(
        blocks=blocks,
        short=short,
        long=long,
        invalid=invalid,
        compared=compared,
        referenced=referenced,
    )

    # Assert
    assert "block 1 not read" in describe(Mode.HEAD, 1, found, Trend.FIRST)


def test_a_read_with_nothing_in_it_is_console_error_22() -> None:
    # Arrange
    expected = 0x22

    # Act
    side = reference_side()

    # Assert
    assert sample(pack_raw03(bytes(4000)), side).console_error == expected
    assert sample(pack_raw03(bytes(4000))).console_error == 0x22


def test_a_missing_first_block_is_console_error_22() -> None:
    # Arrange
    side = reference_side()

    # Act
    found = sample(stream(side, keep=slice(2, None)), side)

    # Assert
    assert found.console_error == 0x22
    assert "console error 22, block 1 expected" in describe(Mode.HEAD, 1, found, Trend.FIRST)


def test_a_missing_file_header_is_console_error_24() -> None:
    # Arrange
    side = reference_side()
    payloads = [block.payload for block in side.blocks]

    # Act
    found = sample(encode_block_stream(payloads[:2] + payloads[4:]), side)

    # Assert
    assert found.missing[0] == 2
    assert found.console_error == 0x24


def test_a_block_that_is_found_but_wrong_is_console_error_27() -> None:
    # Arrange
    side = reference_side()

    # Act
    found = sample(nudged(stream(side), shorter=True), side)

    # Assert
    assert found.console_error == 0x27


def test_a_console_error_a_repairer_has_explained_carries_the_hint() -> None:
    # Arrange
    side = reference_side()
    found = sample(stream(side, keep=slice(2, None)), side)

    # Act
    line = describe(Mode.HEAD, 1, found, Trend.FIRST)

    # Assert
    assert f"console error 22, block 1 expected, {REPAIR_HINTS[0x22]}:" in line


def test_a_console_error_without_a_hint_is_named_alone() -> None:
    # Arrange
    side = reference_side()
    payloads = [block.payload for block in side.blocks]
    found = sample(encode_block_stream(payloads[:3] + payloads[4:]), side)

    # Act
    line = describe(Mode.HEAD, 1, found, Trend.FIRST)

    # Assert
    assert found.console_error == 0x25
    assert "console error 25, block 4 expected:" in line


def test_a_clean_read_has_no_console_error() -> None:
    # Arrange
    side = reference_side()

    # Act
    found = sample(stream(side), side)

    # Assert
    assert found.console_error is None
    assert "console error" not in describe(Mode.SPEED, 1, found, Trend.FIRST)


def test_without_a_reference_a_failed_checksum_is_console_error_27() -> None:
    # Arrange
    blocks = (True, False)
    short = 0
    long = 0
    invalid = 0
    compared = 0
    referenced = False

    # Act
    found = SideSample(
        blocks=blocks,
        short=short,
        long=long,
        invalid=invalid,
        compared=compared,
        referenced=referenced,
    )

    # Assert
    assert found.console_error == 0x27
