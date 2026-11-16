from __future__ import annotations

import pytest
from monitor_kit import SKIP_SYNC, Interrupted, Reader, nudged, reference_side, stream

from fdstoolkit.codecs.raw import (
    block_regions,
    block_starts,
    encode_block_stream,
    pack_raw03,
    unpack_raw03,
)
from fdstoolkit.drive.monitor import (
    MAX_READS,
    Mode,
    Trend,
    advice,
    calibrate,
    describe,
    trend,
)
from fdstoolkit.drive.sampling import (
    NOISY_PULSES,
    SPLICE_VALUES,
    HeadReading,
    SpeedReading,
    sample,
)


def test_a_clean_read_of_the_reference_reads_clean() -> None:
    # Arrange
    side = reference_side()

    # Act
    found = sample(stream(side), side)

    # Assert
    assert found.read == found.expected == len(side.blocks)
    assert (found.short, found.long, found.invalid) == (0, 0, 0)
    assert found.speed is SpeedReading.CLEAN
    assert found.head is HeadReading.CLEAN


def test_pulses_read_short_mean_the_drive_runs_fast() -> None:
    # Arrange
    side = reference_side()

    # Act
    found = sample(nudged(stream(side), shorter=True), side)

    # Assert
    assert found.short > found.long
    assert found.speed is SpeedReading.FAST
    assert "lower the motor speed" in advice(Mode.SPEED, found)


def test_pulses_read_long_mean_the_drive_runs_slow() -> None:
    # Arrange
    side = reference_side()

    # Act
    found = sample(nudged(stream(side), shorter=False), side)

    # Assert
    assert found.long > found.short
    assert found.speed is SpeedReading.SLOW
    assert "raise the motor speed" in advice(Mode.SPEED, found)


def test_a_read_with_nothing_in_it_found_no_block() -> None:
    # Arrange
    side = reference_side()

    # Act
    found = sample(pack_raw03(bytes(4000)), side)

    # Assert
    assert found.read == 0
    assert found.speed is SpeedReading.NOTHING
    assert found.head is HeadReading.NOTHING


def test_missing_first_blocks_point_at_the_start_of_the_side() -> None:
    # Arrange
    side = reference_side()

    # Act
    found = sample(stream(side, keep=slice(2, None)), side)

    # Assert
    assert found.missing == (0, 1)
    assert found.head is HeadReading.START


def test_a_missing_file_does_not_shift_the_files_after_it() -> None:
    # Arrange
    side = reference_side()

    # Act
    found = sample(stream(side, keep=slice(4, None)), side)

    # Assert
    assert found.missing == (0, 1, 2, 3)
    assert found.read == len(side.blocks) - 4
    assert (found.short, found.long) == (0, 0)


def test_missing_last_blocks_point_at_the_end_of_the_side() -> None:
    # Arrange
    side = reference_side()

    # Act
    found = sample(stream(side, keep=slice(None, -2)), side)

    # Assert
    assert found.missing == (len(side.blocks) - 2, len(side.blocks) - 1)
    assert found.head is HeadReading.END


def test_a_block_that_reads_wrong_in_the_middle_is_scattered() -> None:
    # Arrange
    side = reference_side()
    payloads = [block.payload for block in side.blocks]
    payloads[3] = payloads[3][:-1] + bytes([payloads[3][-1] ^ 0xFF])

    # Act
    found = sample(encode_block_stream(payloads), side)

    # Assert
    assert found.missing == (3,)
    assert found.head is HeadReading.SCATTERED
    assert found.speed is SpeedReading.ERRORS


def test_without_a_reference_only_the_checksums_judge() -> None:
    # Arrange
    side = reference_side()

    # Act
    found = sample(stream(side))

    # Assert
    assert not found.referenced
    assert found.compared == 0
    assert found.speed is SpeedReading.CLEAN


def test_without_a_reference_a_read_that_stops_early_is_not_clean() -> None:
    # Arrange
    side = reference_side()

    # Act
    found = sample(stream(side, keep=slice(None, 4)))

    # Assert
    assert found.expected == len(side.blocks)
    assert found.missing == tuple(range(4, len(side.blocks)))
    assert found.head is HeadReading.END
    assert found.speed is SpeedReading.ERRORS
    assert found.console_error == 0x21 + 3


def test_without_a_reference_an_unreadable_file_amount_leaves_the_count_to_the_read() -> None:
    # Arrange
    side = reference_side()

    # Act
    found = sample(stream(side, keep=slice(None, 1)))

    # Assert
    assert found.expected == 1
    assert found.speed is SpeedReading.CLEAN


def test_invalid_pulses_outside_the_gaps_are_counted() -> None:
    # Arrange
    side = reference_side()
    values = bytearray(unpack_raw03(stream(side)))
    start = block_starts(bytes(values))[1]
    values[start + SKIP_SYNC] = 3

    # Act
    found = sample(pack_raw03(bytes(values)), side)

    # Assert
    assert found.invalid == 1
    assert found.speed is not SpeedReading.CLEAN


def test_an_invalid_pulse_inside_the_first_block_is_counted() -> None:
    # Arrange
    side = reference_side()
    values = bytearray(unpack_raw03(stream(side)))
    start, _ = block_regions(bytes(values))[0]
    values[start + SKIP_SYNC] = 3

    # Act
    found = sample(pack_raw03(bytes(values)), side)

    # Assert
    assert found.invalid == 1
    assert found.speed is not SpeedReading.CLEAN


def test_a_long_pulse_in_the_splice_after_a_block_is_not_counted() -> None:
    # Arrange
    side = reference_side()
    values = bytearray(unpack_raw03(stream(side)))
    _, end = block_regions(bytes(values))[1]
    values[end + SKIP_SYNC] = 3

    # Act
    found = sample(pack_raw03(bytes(values)), side)

    # Assert
    assert found.invalid == 0


def test_an_invalid_pulse_in_a_gap_past_the_splice_is_counted() -> None:
    # Arrange
    side = reference_side()
    values = bytearray(unpack_raw03(stream(side)))
    _, end = block_regions(bytes(values))[1]
    values[end + SPLICE_VALUES] = 3

    # Act
    found = sample(pack_raw03(bytes(values)), side)

    # Assert
    assert found.invalid == 1


def test_an_invalid_pulse_past_the_last_declared_block_is_not_counted() -> None:
    # Arrange
    side = reference_side()
    values = unpack_raw03(stream(side))
    padded = values + bytes(SPLICE_VALUES) + bytes([3])

    # Act
    found = sample(pack_raw03(padded), side)

    # Assert
    assert found.invalid == 0


def test_an_invalid_pulse_after_the_last_block_of_a_side_missing_blocks_is_counted() -> None:
    # Arrange
    side = reference_side()
    values = unpack_raw03(stream(side, keep=slice(0, -2)))
    padded = values + bytes(SPLICE_VALUES) + bytes([3])

    # Act
    found = sample(pack_raw03(padded), side)

    # Assert
    assert found.invalid == 1
    assert found.read == len(side.blocks) - 2


def test_invalid_pulses_before_the_first_block_are_not_counted() -> None:
    # Arrange
    side = reference_side()
    values = bytearray(unpack_raw03(stream(side)))
    start, _ = block_regions(bytes(values))[0]
    values[start - SPLICE_VALUES] = 3

    # Act
    found = sample(pack_raw03(bytes(values)), side)

    # Assert
    assert found.invalid == 0


def test_a_read_too_noisy_to_frame_any_block_is_noisy() -> None:
    # Arrange
    side = reference_side()
    noise = bytes([3, 0]) * NOISY_PULSES * SKIP_SYNC

    # Act
    found = sample(pack_raw03(noise), side)

    # Assert
    assert found.read == 0
    assert found.invalid == NOISY_PULSES * SKIP_SYNC
    assert found.noisy is True


def test_the_trend_follows_blocks_read_then_errors() -> None:
    # Arrange
    side = reference_side()
    clean = sample(stream(side), side)

    # Act
    broken = sample(stream(side, keep=slice(2, None)), side)

    # Assert
    assert trend(None, clean) is Trend.FIRST
    assert trend(broken, clean) is Trend.BETTER
    assert trend(clean, broken) is Trend.WORSE
    assert trend(clean, clean) is Trend.SAME


def test_a_line_names_the_blocks_the_head_missed() -> None:
    # Arrange
    side = reference_side()
    found = sample(stream(side, keep=slice(2, None)), side)

    # Act
    line = describe(Mode.HEAD, 3, found, Trend.BETTER)

    # Assert
    assert line.startswith(f"read 3: {len(side.blocks) - 2} of {len(side.blocks)} blocks")
    assert "blocks 0 to 1 not read" in line
    assert line.endswith("the start of the side is not read, better than the last read")


def test_a_calibration_reads_until_told_to_stop() -> None:
    # Arrange
    side = reference_side()
    reader = Reader([stream(side, keep=slice(2, None)), stream(side)])
    lines: list[str] = []
    stops = iter([False, False, True])

    # Act
    result = calibrate(
        reader,
        mode=Mode.SPEED,
        reads=10,
        reference=side,
        progress=lines.append,
        stopped=lambda: next(stops),
    )

    # Assert
    assert reader.reads == 2
    assert len(lines) == 2
    assert result.clean
    assert result.headline.startswith("reads clean")


def test_an_interrupt_ends_the_calibration_with_what_was_read() -> None:
    # Arrange
    reader = Interrupted()
    reads = 5

    # Act
    result = calibrate(reader, mode=Mode.SPEED, reads=reads)

    # Assert
    assert result.samples == ()


def test_a_calibration_that_never_read_is_not_clean() -> None:
    # Arrange
    reader = Reader([b""])
    reads = 1

    # Act
    result = calibrate(reader, mode=Mode.HEAD, reads=reads, stopped=lambda: True)

    # Assert
    assert not result.clean
    assert result.headline == "stopped before the first read"


@pytest.mark.parametrize("reads", [0, MAX_READS + 1])
def test_the_read_count_is_bounded(reads: int) -> None:
    # Arrange
    reader = Reader([b""])

    # Act
    with pytest.raises(ValueError, match="between 1 and") as raised:
        calibrate(reader, mode=Mode.SPEED, reads=reads)

    # Assert
    assert raised.type is ValueError
