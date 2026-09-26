from __future__ import annotations

import hashlib

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.calibration import calibration_disk
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.raw import (
    block_starts,
    decode_raw03,
    encode_block_stream,
    pack_raw03,
    unpack_raw03,
)
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Side
from fdstoolkit.drive.monitor import (
    MAX_READS,
    HeadReading,
    Mode,
    Replay,
    SideSample,
    SpeedReading,
    Trend,
    advice,
    calibrate,
    describe,
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
    side = reference_side()

    found = sample(stream(side), side)

    assert found.read == found.expected == len(side.blocks)
    assert (found.short, found.long, found.invalid) == (0, 0, 0)
    assert found.speed is SpeedReading.CLEAN
    assert found.head is HeadReading.CLEAN


def test_pulses_read_short_mean_the_drive_runs_fast() -> None:
    side = reference_side()

    found = sample(nudged(stream(side), shorter=True), side)

    assert found.short > found.long
    assert found.speed is SpeedReading.FAST
    assert "lower the motor speed" in advice(Mode.SPEED, found)


def test_pulses_read_long_mean_the_drive_runs_slow() -> None:
    side = reference_side()

    found = sample(nudged(stream(side), shorter=False), side)

    assert found.long > found.short
    assert found.speed is SpeedReading.SLOW
    assert "raise the motor speed" in advice(Mode.SPEED, found)


def test_a_read_with_nothing_in_it_found_no_block() -> None:
    side = reference_side()

    found = sample(pack_raw03(bytes(4000)), side)

    assert found.read == 0
    assert found.speed is SpeedReading.NOTHING
    assert found.head is HeadReading.NOTHING


def test_missing_first_blocks_point_at_the_start_of_the_side() -> None:
    side = reference_side()

    found = sample(stream(side, keep=slice(2, None)), side)

    assert found.missing == (0, 1)
    assert found.head is HeadReading.START


def test_a_missing_file_does_not_shift_the_files_after_it() -> None:
    side = reference_side()

    found = sample(stream(side, keep=slice(4, None)), side)

    assert found.missing == (0, 1, 2, 3)
    assert found.read == len(side.blocks) - 4
    assert (found.short, found.long) == (0, 0)


def test_missing_last_blocks_point_at_the_end_of_the_side() -> None:
    side = reference_side()

    found = sample(stream(side, keep=slice(None, -2)), side)

    assert found.missing == (len(side.blocks) - 2, len(side.blocks) - 1)
    assert found.head is HeadReading.END


def test_a_block_that_reads_wrong_in_the_middle_is_scattered() -> None:
    side = reference_side()
    payloads = [block.payload for block in side.blocks]
    payloads[3] = payloads[3][:-1] + bytes([payloads[3][-1] ^ 0xFF])

    found = sample(encode_block_stream(payloads), side)

    assert found.missing == (3,)
    assert found.head is HeadReading.SCATTERED
    assert found.speed is SpeedReading.ERRORS


def test_without_a_reference_only_the_checksums_judge() -> None:
    side = reference_side()

    found = sample(stream(side))

    assert not found.referenced
    assert found.compared == 0
    assert found.speed is SpeedReading.CLEAN


def test_without_a_reference_a_read_that_stops_early_is_not_clean() -> None:
    side = reference_side()

    found = sample(stream(side, keep=slice(None, 4)))

    assert found.expected == len(side.blocks)
    assert found.missing == tuple(range(4, len(side.blocks)))
    assert found.head is HeadReading.END
    assert found.speed is SpeedReading.ERRORS
    assert found.console_error == 0x21 + 3


def test_without_a_reference_an_unreadable_file_amount_leaves_the_count_to_the_read() -> None:
    side = reference_side()

    found = sample(stream(side, keep=slice(None, 1)))

    assert found.expected == 1
    assert found.speed is SpeedReading.CLEAN


def test_invalid_pulses_outside_the_gaps_are_counted() -> None:
    side = reference_side()
    values = bytearray(unpack_raw03(stream(side)))
    start = block_starts(bytes(values))[1]
    values[start + SKIP_SYNC] = 3

    found = sample(pack_raw03(bytes(values)), side)

    assert found.invalid == 1
    assert found.speed is not SpeedReading.CLEAN


def test_the_trend_follows_blocks_read_then_errors() -> None:
    side = reference_side()
    clean = sample(stream(side), side)
    broken = sample(stream(side, keep=slice(2, None)), side)

    assert trend(None, clean) is Trend.FIRST
    assert trend(broken, clean) is Trend.BETTER
    assert trend(clean, broken) is Trend.WORSE
    assert trend(clean, clean) is Trend.SAME


def test_a_line_names_the_blocks_the_head_missed() -> None:
    side = reference_side()
    found = sample(stream(side, keep=slice(2, None)), side)

    line = describe(Mode.HEAD, 3, found, Trend.BETTER)

    assert line.startswith(f"read 3: {len(side.blocks) - 2} of {len(side.blocks)} blocks")
    assert "blocks 0 to 1 not read" in line
    assert line.endswith("the start of the side is not read, better than the last read")


def test_a_calibration_reads_until_told_to_stop() -> None:
    side = reference_side()
    reader = Reader([stream(side, keep=slice(2, None)), stream(side)])
    lines: list[str] = []
    stops = iter([False, False, True])

    result = calibrate(
        reader,
        mode=Mode.SPEED,
        reads=10,
        reference=side,
        progress=lines.append,
        stopped=lambda: next(stops),
    )

    assert reader.reads == 2
    assert len(lines) == 2
    assert result.clean
    assert result.headline.startswith("reads clean")


class Interrupted:
    def read_raw_side(self, *, what: str) -> bytes:
        del what
        raise KeyboardInterrupt


def test_an_interrupt_ends_the_calibration_with_what_was_read() -> None:
    result = calibrate(Interrupted(), mode=Mode.SPEED, reads=5)

    assert result.samples == ()


def test_a_calibration_that_never_read_is_not_clean() -> None:
    result = calibrate(Reader([b""]), mode=Mode.HEAD, reads=1, stopped=lambda: True)

    assert not result.clean
    assert result.headline == "stopped before the first read"


@pytest.mark.parametrize("reads", [0, MAX_READS + 1])
def test_the_read_count_is_bounded(reads: int) -> None:
    with pytest.raises(ValueError, match="between 1 and"):
        calibrate(Reader([b""]), mode=Mode.SPEED, reads=reads)


def test_misread_pulses_that_lean_neither_way_are_not_speed() -> None:
    found = SideSample(
        blocks=(True, False), short=10, long=10, invalid=0, compared=100, referenced=True
    )

    assert found.speed is SpeedReading.ERRORS


def test_a_line_names_blocks_missed_apart_one_by_one() -> None:
    found = SideSample(
        blocks=(True, False, True, False), short=0, long=0, invalid=0, compared=0, referenced=False
    )

    line = describe(Mode.HEAD, 1, found, Trend.FIRST)

    assert "blocks 1, 3 not read" in line


def test_a_calibration_needs_no_progress_callback() -> None:
    side = reference_side()

    result = calibrate(Reader([stream(side)]), mode=Mode.HEAD, reads=1, reference=side)

    assert result.clean


def test_a_line_names_a_single_missed_block() -> None:
    found = SideSample(
        blocks=(True, False, True), short=0, long=0, invalid=0, compared=0, referenced=False
    )

    assert "block 1 not read" in describe(Mode.HEAD, 1, found, Trend.FIRST)


def test_a_read_with_nothing_in_it_is_console_error_22() -> None:
    side = reference_side()

    assert sample(pack_raw03(bytes(4000)), side).console_error == 0x22
    assert sample(pack_raw03(bytes(4000))).console_error == 0x22


def test_a_missing_first_block_is_console_error_22() -> None:
    side = reference_side()

    found = sample(stream(side, keep=slice(2, None)), side)

    assert found.console_error == 0x22
    assert "console error 22, block 1 expected" in describe(Mode.HEAD, 1, found, Trend.FIRST)


def test_a_missing_file_header_is_console_error_24() -> None:
    side = reference_side()
    payloads = [block.payload for block in side.blocks]

    found = sample(encode_block_stream(payloads[:2] + payloads[4:]), side)

    assert found.missing[0] == 2
    assert found.console_error == 0x24


def test_a_block_that_is_found_but_wrong_is_console_error_27() -> None:
    side = reference_side()

    found = sample(nudged(stream(side), shorter=True), side)

    assert found.console_error == 0x27


def test_a_clean_read_has_no_console_error() -> None:
    side = reference_side()

    found = sample(stream(side), side)

    assert found.console_error is None
    assert "console error" not in describe(Mode.SPEED, 1, found, Trend.FIRST)


def test_without_a_reference_a_failed_checksum_is_console_error_27() -> None:
    found = SideSample(
        blocks=(True, False), short=0, long=0, invalid=0, compared=0, referenced=False
    )

    assert found.console_error == 0x27


def test_a_bracketed_calibration_asks_for_a_step_between_reads_and_finds_the_middle() -> None:
    side = reference_side()
    clean = stream(side)
    lost = stream(side, keep=slice(2, None))
    reader = Reader([clean, clean, lost, lost, clean, clean, lost, lost])
    asked: list[str] = []

    def ask(prompt: str) -> bool:
        asked.append(prompt)
        return True

    result = calibrate(reader, mode=Mode.HEAD, reads=20, reference=side, bracket=ask)

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
    side = reference_side()
    reader = Reader([stream(side)])

    result = calibrate(reader, mode=Mode.SPEED, reads=5, reference=side, bracket=decline)

    assert reader.reads == 1
    assert result.bracket is not None
    assert "keep turning" in result.headline


def test_a_replay_hands_back_saved_reads_in_order_and_then_stops() -> None:
    replay = Replay((b"\x01", b"\x02"))

    first = replay.read_raw_side(what="calibration read 1")
    second = replay.read_raw_side(what="calibration read 2")

    assert (first, second) == (b"\x01", b"\x02")
    assert replay.reads == 2
    with pytest.raises(ValueError, match="calibration read 3: the captures hold 2 reads"):
        replay.read_raw_side(what="calibration read 3")


def test_without_a_reference_a_block_read_clean_earlier_becomes_the_reference() -> None:
    side = reference_side()
    reader = Reader([stream(side), nudged(stream(side), shorter=True)])

    result = calibrate(reader, mode=Mode.SPEED, reads=2)

    first, second = result.samples
    assert not first.referenced
    assert second.referenced
    assert second.short > second.long
    assert second.speed is SpeedReading.FAST


def test_without_a_reference_nothing_is_compared_before_any_block_reads_clean() -> None:
    side = reference_side()
    reader = Reader([nudged(stream(side), shorter=True)])

    result = calibrate(reader, mode=Mode.SPEED, reads=1)

    assert not result.samples[0].referenced
    assert result.samples[0].compared == 0


def test_the_calibration_disk_is_its_own_reference_from_the_first_read() -> None:
    side = calibration_disk().sides[0]
    heard: list[str] = []
    damaged = nudged(stream(side, keep=slice(0, 4)), shorter=True, first=3)
    reader = Reader([pack_raw03(unpack_raw03(damaged) + bytes(TRAILING_GAP))])

    result = calibrate(reader, mode=Mode.SPEED, reads=1, progress=heard.append)

    assert result.samples[0].referenced
    assert result.samples[0].speed is SpeedReading.FAST
    assert any("calibration disk" in line for line in heard)


def test_learning_keeps_the_first_clean_copy_and_ignores_failed_blocks() -> None:
    side = reference_side()
    clean, _ = decode_raw03(unpack_raw03(stream(side)) + bytes(TRAILING_GAP))
    broken, _ = decode_raw03(unpack_raw03(nudged(stream(side), shorter=True)) + bytes(TRAILING_GAP))

    learned = learn(learn({}, broken.blocks), clean.blocks)

    assert len(learned) == len(side.blocks)
    assert learn(learned, clean.blocks) == learned


def test_head_advice_names_a_fine_turn_for_a_head_nearly_in_place() -> None:
    side = reference_side()

    found = sample(stream(side, keep=slice(2, None)), side)

    assert "45 degrees" in advice(Mode.HEAD, found)
    assert "one track" in advice(Mode.HEAD, found)


def test_a_speed_headline_counts_the_verdicts_of_the_last_reads() -> None:
    side = reference_side()
    fast = nudged(stream(side), shorter=True)
    reader = Reader([stream(side), fast, stream(side), stream(side)])

    result = calibrate(reader, mode=Mode.SPEED, reads=4, reference=side)

    assert result.spread == {"reads clean": 3, "reads fast": 1}
    assert result.headline.endswith("; the last 4 reads: 3 reads clean, 1 reads fast")


def test_a_single_read_has_no_spread_in_its_headline() -> None:
    side = reference_side()

    result = calibrate(Reader([stream(side)]), mode=Mode.SPEED, reads=1, reference=side)

    assert "; the last" not in result.headline
