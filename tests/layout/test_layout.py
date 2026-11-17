from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.calibration import calibration_disk
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.raw import block_pulses, pack_raw03
from fdstoolkit.drive.captures import Bundle, Capture
from fdstoolkit.identify.layout import Layout, layout_of, layouts_for

FIXTURE: Final = Path(__file__).resolve().parents[1] / "fixtures" / "fdsstick"
LEAD_IN: Final = 14000
GAP: Final = 990
GAP_STEP: Final = 9
GAP_STEPS: Final = 5
TAIL: Final = 2000
SWITCH_OFF_NOISE: Final = bytes([1, 3, 0, 3, 3, 1, 0, 3])


def real_capture() -> bytes:
    named: dict[str, str] = json.loads((FIXTURE / "calibration-side.json").read_text())
    return (FIXTURE / named["capture"]).read_bytes()


def payloads() -> list[bytes]:
    return [block.payload for block in calibration_disk(1).sides[0].blocks]


def side_of(blocks: list[bytes], *, noise: bytes, step: int) -> bytes:
    values = bytearray(LEAD_IN)
    for index, payload in enumerate(blocks):
        if index:
            values += bytes(GAP + step * (index % GAP_STEPS))
        values += block_pulses(payload) + noise
    values += bytes(TAIL)
    return pack_raw03(bytes(values))


def test_a_side_the_fdsstick_wrote_reads_as_streamed() -> None:
    # Arrange
    captures = [real_capture()]

    # Act
    reading = layout_of(captures)

    # Assert
    assert reading.layout is Layout.STREAMED
    assert reading.quiet_endings == reading.endings
    assert reading.gap_spread is not None
    assert reading.gap_spread <= 1


def test_blocks_ending_in_noise_with_uneven_gaps_read_as_duplicated() -> None:
    # Arrange
    capture = side_of(payloads(), noise=SWITCH_OFF_NOISE, step=GAP_STEP)

    # Act
    reading = layout_of([capture])

    # Assert
    assert reading.layout is Layout.DUPLICATED
    assert reading.quiet_endings == 0
    assert reading.gap_spread == 36


def test_quiet_endings_with_uneven_gaps_settle_nothing() -> None:
    # Arrange
    capture = side_of(payloads(), noise=b"", step=GAP_STEP)

    # Act
    reading = layout_of([capture])

    # Assert
    assert reading.layout is Layout.UNSETTLED
    assert "do not settle" in reading.note()


def test_noisy_endings_with_even_gaps_settle_nothing() -> None:
    # Arrange
    capture = side_of(payloads(), noise=SWITCH_OFF_NOISE, step=0)

    # Act
    reading = layout_of([capture])

    # Assert
    assert reading.layout is Layout.UNSETTLED


def test_a_side_with_too_few_blocks_settles_nothing() -> None:
    # Arrange
    capture = side_of(payloads()[:1], noise=b"", step=0)

    # Act
    reading = layout_of([capture])

    # Assert
    assert reading.layout is Layout.UNSETTLED
    assert reading.gap_spread is None
    assert "too few clean blocks" in reading.note()


def test_every_read_of_a_side_is_counted() -> None:
    # Arrange
    capture = real_capture()

    # Act
    reading = layout_of([capture, capture])

    # Assert
    assert reading.reads == 2
    assert reading.endings == 2 * layout_of([capture]).endings


def test_a_streamed_side_names_what_a_factory_side_shows() -> None:
    # Arrange
    reading = layout_of([real_capture()])

    # Act
    note = reading.note()

    # Assert
    assert note.startswith("the captures show a side written in one stream")
    assert "18 to 73 bits" in note
    assert "only factory reference is one disk" in note


def test_a_duplicated_side_says_so() -> None:
    # Arrange
    reading = layout_of([side_of(payloads(), noise=SWITCH_OFF_NOISE, step=GAP_STEP)])

    # Act
    note = reading.note()

    # Assert
    assert note.startswith("the captures show a duplicator's layout")


def bundle_of(*sides: int) -> Bundle:
    capture = real_capture()
    return Bundle(
        captures=tuple(Capture(side=side, read=1, data=capture) for side in sides),
        image="disk.fds",
        created="2026-11-13T00:00:00Z",
    )


def test_only_the_sides_the_image_has_are_measured() -> None:
    # Arrange
    bundle = bundle_of(0, 1)

    # Act
    layouts = layouts_for(calibration_disk(1), bundle)

    # Assert
    assert list(layouts) == [0]
    assert layouts[0].layout is Layout.STREAMED


def test_captures_of_another_disk_are_refused() -> None:
    # Arrange
    other, _ = decode(blank_image(sides=1, headered=False, formatted=True))

    # Act
    with pytest.raises(ValueError, match="another disk") as raised:
        layouts_for(other, bundle_of(0))

    # Assert
    assert raised.type is ValueError


def saved_side(blocks: list[bytes], rewritten: int) -> bytes:
    values = bytearray(LEAD_IN)
    for index, payload in enumerate(blocks):
        if index:
            values += bytes(GAP + GAP_STEP * (index % GAP_STEPS))
        values += block_pulses(payload) + (b"" if index == rewritten else SWITCH_OFF_NOISE)
    values += bytes(TAIL)
    return pack_raw03(bytes(values))


def test_a_block_ending_clean_on_a_duplicated_side_reads_as_rewritten() -> None:
    # Arrange
    blocks = payloads()
    rewritten = len(blocks) - 1
    captures = [saved_side(blocks, rewritten), saved_side(blocks, rewritten)]

    # Act
    reading = layout_of(captures)

    # Assert
    assert reading.layout is Layout.DUPLICATED
    assert [block for block, _ in reading.rewritten] == [rewritten]
    assert reading.rewritten[0][1] != ""
    assert reading.rewritten_note().endswith(
        "as a game writes its save; a console's save has not been measured yet, "
        "so this mark is not confirmed"
    )


def test_a_block_ending_clean_in_only_one_read_is_not_named() -> None:
    # Arrange
    blocks = payloads()
    noisy = side_of(blocks, noise=SWITCH_OFF_NOISE, step=GAP_STEP)

    # Act
    reading = layout_of([saved_side(blocks, len(blocks) - 1), noisy])

    # Assert
    assert reading.rewritten == ()


def test_a_streamed_side_names_no_rewritten_block() -> None:
    # Arrange
    captures = [real_capture()]

    # Act
    reading = layout_of(captures)

    # Assert
    assert reading.quiet_blocks
    assert reading.rewritten == ()


def test_a_rewritten_disk_information_block_is_named_by_number_alone() -> None:
    # Arrange
    blocks = payloads()
    captures = [saved_side(blocks, 0)]

    # Act
    reading = layout_of(captures)

    # Assert
    assert reading.rewritten == ((0, ""),)
    assert reading.rewritten_note().startswith("block 0 end with no stray pulses")


def test_no_capture_names_no_block() -> None:
    # Arrange
    captures: list[bytes] = []

    # Act
    reading = layout_of(captures)

    # Assert
    assert reading.quiet_blocks == ()


def test_a_data_block_whose_header_was_lost_is_named_by_number_alone() -> None:
    # Arrange
    blocks = payloads()
    without_header = [*blocks[:-2], blocks[-1]]
    last = len(without_header) - 1

    # Act
    reading = layout_of([saved_side(without_header, last)])

    # Assert
    assert reading.rewritten == ((last, ""),)
