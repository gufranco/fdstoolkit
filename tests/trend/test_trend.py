from __future__ import annotations

from dataclasses import replace
from typing import Final

from fdstoolkit.history.logbook import Entry, EntryKind
from fdstoolkit.history.trend import trend_lines, trend_of

FIRST: Final = Entry(
    run="run-1",
    recorded="2026-11-01T10:00:00Z",
    kind=EntryKind.DUMP,
    disk="disk-0123456789abcdef",
    title="ZEL",
    stick="FDS00042",
    drive="hvc-022",
    grade="clean",
    weak=((0, 3),),
)
SECOND: Final = replace(
    FIRST,
    run="run-2",
    recorded="2026-11-16T17:00:00Z",
    grade="marginal",
    weak=((0, 3), (0, 7), (1, 2)),
)


def test_two_dumps_name_the_blocks_that_weakened_between_them() -> None:
    # Arrange
    entries = (FIRST, SECOND)

    # Act
    found = trend_of(entries)

    # Assert
    assert found.weakened == ((0, 7), (1, 2))
    assert found.settled == ()
    assert found.since == FIRST


def test_blocks_that_read_clean_again_are_named_too() -> None:
    # Arrange
    entries = (SECOND, replace(FIRST, run="run-3", recorded="2026-11-20T09:00:00Z"))

    # Act
    found = trend_of(entries)

    # Assert
    assert found.weakened == ()
    assert found.settled == ((0, 7), (1, 2))


def test_the_latest_entry_is_compared_with_the_last_of_its_own_kind() -> None:
    # Arrange
    graded = replace(
        FIRST, run="run-g", recorded="2026-11-10T08:00:00Z", kind=EntryKind.GRADE, weak=()
    )

    # Act
    found = trend_of((FIRST, graded, SECOND))

    # Assert
    assert found.since == FIRST


def test_a_single_entry_has_nothing_to_compare_with() -> None:
    # Arrange
    entries = (FIRST,)

    # Act
    found = trend_of(entries)

    # Assert
    assert found.since is None
    assert found.weakened == ()


def test_an_empty_history_says_so() -> None:
    # Arrange
    entries: tuple[Entry, ...] = ()

    # Act
    lines = trend_lines(trend_of(entries))

    # Assert
    assert lines == ("nothing is logged for this yet",)


def test_the_lines_list_each_entry_then_what_changed() -> None:
    # Arrange
    found = trend_of((FIRST, SECOND))

    # Act
    lines = trend_lines(found)

    # Assert
    assert lines == (
        "2026-11-01 10:00  dump         clean      ZEL  1 weak: side 0 block 3",
        (
            "2026-11-16 17:00  dump         marginal   ZEL  3 weak: side 0 block 3, "
            "side 0 block 7, side 1 block 2"
        ),
        "since the dump of 2026-11-01 10:00, 2 block(s) weakened: side 0 block 7, side 1 block 2",
    )


def test_an_entry_with_no_weak_block_says_so_and_no_change_is_reported() -> None:
    # Arrange
    clean = replace(FIRST, weak=())
    again = replace(clean, run="run-4", recorded="2026-11-02T10:00:00Z")

    # Act
    lines = trend_lines(trend_of((clean, again)))

    # Assert
    assert lines == (
        "2026-11-01 10:00  dump         clean      ZEL  no weak block",
        "2026-11-02 10:00  dump         clean      ZEL  no weak block",
        "since the dump of 2026-11-01 10:00, no block changed",
    )


def test_blocks_reading_clean_again_get_their_own_line() -> None:
    # Arrange
    found = trend_of((SECOND, replace(FIRST, run="run-5", recorded="2026-11-20T09:00:00Z")))

    # Act
    lines = trend_lines(found)

    # Assert
    assert lines[-1] == (
        "since the dump of 2026-11-16 17:00, 2 block(s) read clean again: side 0 block 7, "
        "side 1 block 2"
    )
