from __future__ import annotations

import pytest
from monitor_kit import (
    SKIP_SYNC,
    STRAY_SPACING,
    TRAILING_GAP,
    Reader,
    closing_pulse_read_long,
    decline,
    noisy_sample,
    nudged,
    reference_side,
    stream,
    with_strays,
)

from fdstoolkit.build.calibration import calibration_disk
from fdstoolkit.codecs.raw import (
    block_starts,
    decode_raw03,
    pack_raw03,
    unpack_raw03,
)
from fdstoolkit.core.bitstream import LEAD_IN_BITS
from fdstoolkit.drive.monitor import (
    FIXED_SPOT,
    NOISY_READ,
    Calibration,
    Mode,
    Replay,
    Trend,
    advice,
    calibrate,
    describe,
)
from fdstoolkit.drive.sampling import (
    NOISY_PULSES,
    SpeedReading,
    lean,
    learn,
    sample,
)


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
