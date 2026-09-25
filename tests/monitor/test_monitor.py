from __future__ import annotations

import hashlib

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.raw import block_starts, encode_block_stream, pack_raw03, unpack_raw03
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Side
from fdstoolkit.drive.monitor import (
    MAX_READS,
    HeadReading,
    Mode,
    SideSample,
    SpeedReading,
    Trend,
    advice,
    calibrate,
    describe,
    sample,
    trend,
)
from fdstoolkit.edit.files import FileSpec, insert_file

FILES = 4
SKIP_SYNC = 40
NUDGED = 60

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


def nudged(packed: bytes, *, shorter: bool) -> bytes:
    values = bytearray(unpack_raw03(packed))
    for start in block_starts(bytes(values)):
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
