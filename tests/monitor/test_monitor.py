from __future__ import annotations

import hashlib

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.calibration import calibration_disk
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.raw import (
    LEAD_IN_BITS,
    block_pulses,
    block_regions,
    block_starts,
    decode_raw03,
    encode_block_stream,
    pack_raw03,
    unpack_raw03,
)
from fdstoolkit.core.bios import REPAIR_HINTS
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Side
from fdstoolkit.drive.monitor import (
    FIXED_SPOT,
    MAX_READS,
    NOISY_PULSES,
    NOISY_READ,
    SPLICE_VALUES,
    Calibration,
    HeadReading,
    Mode,
    Replay,
    SideSample,
    SpeedReading,
    Trend,
    advice,
    calibrate,
    describe,
    lean,
    learn,
    sample,
    trend,
)
from fdstoolkit.edit.files import FileSpec, insert_file

FILES = 4
SKIP_SYNC = 40
NUDGED = 60
TRAILING_GAP = 4000

DIGESTS_PER_FILE = 8


def file_bytes(number: int) -> bytes:
    return b"".join(
        hashlib.sha256(f"file {number} part {part}".encode()).digest()
        for part in range(DIGESTS_PER_FILE)
    )


def reference_side() -> Side:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="CAL"))
    for number in range(FILES):
        disk = insert_file(
            disk,
            side=0,
            spec=FileSpec(
                name=f"FILE{number:04d}",
                address=0x6000,
                kind=FileKind.PROGRAM,
                data=file_bytes(number),
            ),
        )
    return disk.sides[0]


def stream(side: Side, *, keep: slice = slice(None)) -> bytes:
    return encode_block_stream([block.payload for block in side.blocks[keep]])


def nudged(packed: bytes, *, shorter: bool, first: int = 0) -> bytes:
    values = bytearray(unpack_raw03(packed))
    for start in block_starts(bytes(values))[first:]:
        changed = 0
        for index in range(start + SKIP_SYNC, len(values)):
            if changed == NUDGED:
                break
            value = values[index]
            if shorter and value > 0:
                values[index] = value - 1
                changed += 1
            elif not shorter and value < 2:
                values[index] = value + 1
                changed += 1
    return pack_raw03(bytes(values))


class Reader:
    def __init__(self, captures: list[bytes]) -> None:
        self.captures = captures
        self.reads = 0

    def read_raw_side(self, *, what: str) -> bytes:
        del what
        capture = self.captures[min(self.reads, len(self.captures) - 1)]
        self.reads += 1
        return capture


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


class Interrupted:
    def read_raw_side(self, *, what: str) -> bytes:
        del what
        raise KeyboardInterrupt


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


def test_a_bracketed_calibration_asks_for_a_step_between_reads_and_finds_the_middle() -> None:
    # Arrange
    side = reference_side()
    clean = stream(side)
    lost = stream(side, keep=slice(2, None))
    reader = Reader([clean, clean, lost, lost, clean, clean, lost, lost])
    asked: list[str] = []

    def ask(prompt: str) -> bool:
        asked.append(prompt)
        return True

    # Act
    result = calibrate(reader, mode=Mode.HEAD, reads=20, reference=side, bracket=ask)

    # Assert
    assert reader.reads == 8
    assert len(asked) == 7
    assert "the other way" in asked[3]
    assert "do not turn" in asked[-1]
    assert result.bracket is not None
    assert result.bracket.done
    assert result.headline.startswith("it reads across")


def decline(prompt: str) -> bool:
    del prompt
    return False


def test_declining_a_step_ends_a_bracketed_calibration() -> None:
    # Arrange
    side = reference_side()
    reader = Reader([stream(side)])

    # Act
    result = calibrate(reader, mode=Mode.SPEED, reads=5, reference=side, bracket=decline)

    # Assert
    assert reader.reads == 1
    assert result.bracket is not None
    assert "keep turning" in result.headline


def test_a_replay_hands_back_saved_reads_in_order_and_then_stops() -> None:
    # Arrange
    replay = Replay((b"\x01", b"\x02"))
    first = replay.read_raw_side(what="calibration read 1")
    second = replay.read_raw_side(what="calibration read 2")
    assert (first, second) == (b"\x01", b"\x02")
    assert replay.reads == 2

    # Act
    with pytest.raises(ValueError, match="calibration read 3: the captures hold 2 reads") as raised:
        replay.read_raw_side(what="calibration read 3")

    # Assert
    assert raised.type is ValueError


def test_without_a_reference_a_block_read_clean_earlier_becomes_the_reference() -> None:
    # Arrange
    side = reference_side()
    reader = Reader([stream(side), nudged(stream(side), shorter=True)])

    # Act
    result = calibrate(reader, mode=Mode.SPEED, reads=2)

    # Assert
    first, second = result.samples
    assert not first.referenced
    assert second.referenced
    assert second.short > second.long
    assert second.speed is SpeedReading.FAST


def test_without_a_reference_nothing_is_compared_before_any_block_reads_clean() -> None:
    # Arrange
    side = reference_side()
    reader = Reader([nudged(stream(side), shorter=True)])

    # Act
    result = calibrate(reader, mode=Mode.SPEED, reads=1)

    # Assert
    assert not result.samples[0].referenced
    assert result.samples[0].compared == 0


def test_the_calibration_disk_is_its_own_reference_from_the_first_read() -> None:
    # Arrange
    side = calibration_disk().sides[0]
    heard: list[str] = []
    damaged = nudged(stream(side, keep=slice(0, 4)), shorter=True, first=3)
    reader = Reader([pack_raw03(unpack_raw03(damaged) + bytes(TRAILING_GAP))])

    # Act
    result = calibrate(reader, mode=Mode.SPEED, reads=1, progress=heard.append)

    # Assert
    assert result.samples[0].referenced
    assert result.samples[0].speed is SpeedReading.FAST
    assert any("calibration disk" in line for line in heard)


def test_learning_keeps_the_first_clean_copy_and_ignores_failed_blocks() -> None:
    # Arrange
    side = reference_side()
    clean, _ = decode_raw03(unpack_raw03(stream(side)) + bytes(TRAILING_GAP))
    broken, _ = decode_raw03(unpack_raw03(nudged(stream(side), shorter=True)) + bytes(TRAILING_GAP))

    # Act
    learned = learn(learn({}, broken.blocks), clean.blocks)

    # Assert
    assert len(learned) == len(side.blocks)
    assert learn(learned, clean.blocks) == learned


def test_head_advice_names_a_fine_turn_for_a_head_nearly_in_place() -> None:
    # Arrange
    side = reference_side()

    # Act
    found = sample(stream(side, keep=slice(2, None)), side)

    # Assert
    assert "45 degrees" in advice(Mode.HEAD, found)
    assert "one track" in advice(Mode.HEAD, found)


def test_a_speed_headline_counts_the_verdicts_of_the_last_reads() -> None:
    # Arrange
    side = reference_side()
    fast = nudged(stream(side), shorter=True)
    reader = Reader([stream(side), fast, stream(side), stream(side)])

    # Act
    result = calibrate(reader, mode=Mode.SPEED, reads=4, reference=side)

    # Assert
    assert result.spread == {"reads clean": 3, "reads fast": 1}
    assert result.headline.endswith("; the last 4 reads: 3 reads clean, 1 reads fast")


def test_a_single_read_has_no_spread_in_its_headline() -> None:
    # Arrange
    side = reference_side()

    # Act
    result = calibrate(Reader([stream(side)]), mode=Mode.SPEED, reads=1, reference=side)

    # Assert
    assert "; the last" not in result.headline


def test_a_fast_drive_still_reads_fast_when_every_block_gained_a_pulse() -> None:
    # Arrange
    side = reference_side()
    values = unpack_raw03(nudged(stream(side), shorter=True))
    for start in reversed(block_starts(values)):
        spot = start + SKIP_SYNC // 2
        values = values[:spot] + values[spot : spot + 1] + values[spot:]
    slipped = pack_raw03(values)

    # Act
    found = sample(slipped, side)

    # Assert
    assert lean(found.short, found.long) is SpeedReading.FAST
    assert found.long * 10 < found.short


def noisy_sample(*, invalid: int, leaning: int) -> SideSample:
    return SideSample(
        blocks=(True, False),
        short=leaning,
        long=0,
        invalid=invalid,
        compared=1000,
        referenced=True,
    )


def test_a_read_failing_mostly_on_invalid_pulses_names_the_read_line_resistor() -> None:
    # Arrange
    samples = (noisy_sample(invalid=NOISY_PULSES, leaning=2),)

    # Act
    result = Calibration(mode=Mode.SPEED, samples=samples)

    # Assert
    assert result.headline.endswith(NOISY_READ)
    assert "10k on the READ DATA pin" in result.headline


def test_a_read_whose_failures_lean_with_speed_carries_no_noise_hint() -> None:
    # Arrange
    samples = (noisy_sample(invalid=NOISY_PULSES, leaning=NOISY_PULSES),)

    # Act
    result = Calibration(mode=Mode.SPEED, samples=samples)

    # Assert
    assert NOISY_READ not in result.headline


STRAYS = 20
STRAY_SPACING = 40
STRAY_START = 60
DATA_BLOCK = 3


def with_strays(side: Side, *, shift: int, lead: int) -> bytes:
    values = bytearray(unpack_raw03(stream(side)))
    start, _ = block_regions(bytes(values))[DATA_BLOCK]
    for number in range(STRAYS):
        values[start + STRAY_START + number * STRAY_SPACING + shift] = 3
    return pack_raw03(bytes(lead) + bytes(values))


def test_stray_pulses_at_the_same_places_on_two_reads_name_the_disk() -> None:
    # Arrange
    side = reference_side()
    reads = (
        sample(with_strays(side, shift=0, lead=0), side),
        sample(with_strays(side, shift=0, lead=STRAY_SPACING * 13), side),
    )

    # Act
    headline = Calibration(mode=Mode.SPEED, samples=reads).headline

    # Assert
    assert headline.endswith(FIXED_SPOT)
    assert NOISY_READ not in headline


def test_stray_pulses_that_move_between_reads_name_the_read_line() -> None:
    # Arrange
    side = reference_side()
    reads = (
        sample(with_strays(side, shift=0, lead=0), side),
        sample(with_strays(side, shift=STRAY_SPACING // 4, lead=0), side),
    )

    # Act
    headline = Calibration(mode=Mode.SPEED, samples=reads).headline

    # Assert
    assert headline.endswith(NOISY_READ)


def test_noisy_reads_with_no_recorded_positions_keep_the_read_line_hint() -> None:
    # Arrange
    reads = (
        noisy_sample(invalid=NOISY_PULSES, leaning=0),
        noisy_sample(invalid=NOISY_PULSES, leaning=0),
    )

    # Act
    headline = Calibration(mode=Mode.SPEED, samples=reads).headline

    # Assert
    assert headline.endswith(NOISY_READ)


def test_reads_too_noisy_for_any_block_with_noise_at_the_same_places_name_the_disk() -> None:
    # Arrange
    side = reference_side()
    noise = pack_raw03(bytes([3, 0]) * NOISY_PULSES * SKIP_SYNC)

    # Act
    headline = Calibration(
        mode=Mode.SPEED, samples=(sample(noise, side), sample(noise, side))
    ).headline

    # Assert
    assert headline.endswith(FIXED_SPOT)


CLOSING_BLOCK = 5


def closing_pulse_read_long(side: Side) -> bytes:
    values = bytearray(unpack_raw03(stream(side)))
    start = block_starts(bytes(values))[CLOSING_BLOCK]
    closing = start + len(block_pulses(side.blocks[CLOSING_BLOCK].payload)) - 1
    values[closing] = 2
    return pack_raw03(bytes(values))


def test_a_closing_pulse_read_long_is_not_a_speed_error_against_a_reference() -> None:
    # Arrange
    side = reference_side()

    # Act
    found = sample(closing_pulse_read_long(side), side)

    # Assert
    assert (found.short, found.long) == (0, 0)
    assert found.speed is SpeedReading.CLEAN


def test_a_closing_pulse_read_long_is_not_a_speed_error_against_learned_blocks() -> None:
    # Arrange
    side = reference_side()
    learned = learn({}, side.blocks)

    # Act
    found = sample(closing_pulse_read_long(side), None, learned)

    # Assert
    assert (found.short, found.long) == (0, 0)
    assert found.speed is SpeedReading.CLEAN


def test_a_few_invalid_pulses_carry_no_noise_hint() -> None:
    # Arrange
    samples = (noisy_sample(invalid=NOISY_PULSES - 1, leaning=0),)

    # Act
    result = Calibration(mode=Mode.HEAD, samples=samples)

    # Assert
    assert NOISY_READ not in result.headline


def test_a_read_measures_its_lead_in_in_bits() -> None:
    # Arrange
    side = reference_side()

    # Act
    found = sample(stream(side), side)

    # Assert
    assert found.lead_in == LEAD_IN_BITS


def test_a_read_line_names_the_lead_in() -> None:
    # Arrange
    side = reference_side()
    found = sample(stream(side), side)

    # Act
    line = describe(Mode.SPEED, 1, found, Trend.FIRST)

    # Assert
    assert f"0 invalid, lead-in {LEAD_IN_BITS} bits: " in line


def test_a_read_with_no_block_has_no_lead_in() -> None:
    # Arrange
    packed = pack_raw03(bytes([1, 2]) * 200)
    reference = reference_side()

    # Act
    found = sample(packed, reference)

    # Assert
    assert found.lead_in is None
    assert "lead-in" not in describe(Mode.SPEED, 1, found, Trend.FIRST)
