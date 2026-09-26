from __future__ import annotations

from fdstoolkit.drive.bracket import Bracket, Heading, Phase


def walk(readings: list[bool]) -> Bracket:
    state = Bracket()
    for clean in readings:
        state = state.after(clean=clean)
    return state


def test_it_starts_by_turning_the_way_you_chose() -> None:
    state = Bracket()

    assert state.heading is Heading.ONWARD
    assert "the same way" in state.instruction


def test_a_first_clean_read_means_it_is_inside_the_range() -> None:
    state = walk([True])

    assert state.phase is Phase.FIRST_EDGE
    assert state.position == 1


def test_it_keeps_looking_until_a_read_is_clean() -> None:
    state = walk([False, False])

    assert state.phase is Phase.SEEKING
    assert state.heading is Heading.ONWARD
    assert state.position == 2


def test_the_first_failure_after_a_clean_read_turns_it_round() -> None:
    state = walk([True, True, False, False])

    assert state.phase is Phase.SECOND_EDGE
    assert state.heading is Heading.BACK
    assert state.first_edge == 2
    assert state.position == 1
    assert "the other way" in state.instruction


def test_the_second_failure_finds_the_middle() -> None:
    state = walk([True, True, True, False, False, True, True, True, True, False, False])

    assert state.phase is Phase.DONE
    assert state.first_edge == 3
    assert state.second_edge == -2
    assert state.steps_to_middle == 2
    assert state.width == 4
    assert "turn 2 step(s)" in state.verdict


def test_a_range_found_after_failures_is_measured_the_same_way() -> None:
    state = walk([False, True, True, False, False, True, True, False, False])

    assert state.phase is Phase.DONE
    assert state.width == 2
    assert state.steps_to_middle == 1


def test_a_range_of_one_step_puts_it_straight_back_on_that_step() -> None:
    state = walk([True, False, False, True, False, False])

    assert state.phase is Phase.DONE
    assert state.width == 1
    assert state.steps_to_middle == 1


def test_a_finished_bracket_ignores_further_reads() -> None:
    done = walk([True, False, False, True, False, False])

    assert done.after(clean=True) == done


def test_before_it_finishes_the_verdict_says_where_it_is() -> None:
    assert "no read was clean yet" in walk([False]).verdict
    assert "still reads" in walk([True]).verdict
    assert "coming back" in walk([True, False, False]).verdict


def test_an_unfinished_bracket_has_measured_nothing() -> None:
    state = walk([True])

    assert state.width == 0
    assert state.steps_to_middle == 0


def test_one_failed_read_at_an_edge_is_read_again_before_it_counts() -> None:
    state = walk([True, True, False])

    assert state.phase is Phase.FIRST_EDGE
    assert state.first_edge is None
    assert state.position == 2
    assert "do not turn" in state.instruction
    assert "reading again" in state.verdict


def test_a_failure_that_does_not_repeat_moves_on_without_an_edge() -> None:
    state = walk([True, True, False, True])

    assert state.phase is Phase.FIRST_EDGE
    assert state.first_edge is None
    assert state.position == 3
    assert "the same way" in state.instruction
