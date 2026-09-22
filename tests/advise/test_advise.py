from __future__ import annotations

import math

import pytest

from fdstoolkit.drive.advise import Stage, advise
from fdstoolkit.drive.spec import NOMINAL_BIT_RATE_HZ, cell_from_bit_rate

CELL = cell_from_bit_rate(NOMINAL_BIT_RATE_HZ)
RATIOS = (1.0, 1.5, 2.0)


def _capture(
    *,
    rate: float = NOMINAL_BIT_RATE_HZ,
    wow: float = 0.0,
    period: int = 900,
    jitter: float = 0.0,
    pulses: int = 6_000,
) -> tuple[int, ...]:
    cell = cell_from_bit_rate(rate)
    out: list[int] = []
    for index in range(pulses):
        modulation = 1 + wow * math.sin(2 * math.pi * index / period)
        wobble = 1 + jitter * math.sin(index * 2.399963)
        out.append(round(cell * modulation * wobble * RATIOS[index % 3]))
    return tuple(out)


def test_a_drive_at_nominal_with_no_wow_is_settled() -> None:
    result = advise(_capture())

    assert result.settled
    assert not result.actions
    assert result.score > 0.95


def test_a_drive_far_off_speed_gets_a_coarse_action_first() -> None:
    result = advise(_capture(rate=NOMINAL_BIT_RATE_HZ * 0.85))

    assert result.actions
    assert result.actions[0].stage is Stage.COARSE
    assert result.actions[0].subject == "motor speed"


def test_a_drive_inside_spec_but_off_centre_gets_a_fine_action() -> None:
    result = advise(_capture(rate=NOMINAL_BIT_RATE_HZ * 1.04))

    assert not result.settled
    stages = {action.stage for action in result.actions}
    assert Stage.FINE in stages
    assert Stage.COARSE not in stages


def test_a_wobbling_drive_is_told_about_the_belt() -> None:
    result = advise(_capture(wow=0.05))

    subjects = [action.subject for action in result.actions]
    assert "belt and spindle" in subjects


def test_a_slightly_wobbling_drive_gets_only_a_fine_belt_action() -> None:
    result = advise(_capture(wow=0.01))

    belt = [action for action in result.actions if action.subject == "belt and spindle"]
    assert belt
    assert belt[0].stage is Stage.FINE


def test_coarse_actions_are_ranked_before_fine_ones() -> None:
    result = advise(_capture(rate=NOMINAL_BIT_RATE_HZ * 0.85, wow=0.01))

    stages = [action.stage for action in result.actions]
    assert stages == sorted(stages, key=lambda item: 0 if item is Stage.COARSE else 1)


def test_every_action_names_what_was_measured_and_what_to_do() -> None:
    result = advise(_capture(rate=NOMINAL_BIT_RATE_HZ * 0.85))

    for action in result.actions:
        assert action.finding
        assert action.action
        assert 0.0 <= action.gain <= 1.0


def test_a_worse_drive_scores_lower() -> None:
    good = advise(_capture(rate=NOMINAL_BIT_RATE_HZ * 1.005))
    bad = advise(_capture(rate=NOMINAL_BIT_RATE_HZ * 0.85, wow=0.06))

    assert good.score > bad.score
    assert 0.0 <= bad.score <= 1.0


def test_a_settled_drive_renders_as_settled() -> None:
    assert "settled" in advise(_capture()).render()


def test_an_unsettled_drive_renders_each_action() -> None:
    text = advise(_capture(rate=NOMINAL_BIT_RATE_HZ * 0.85)).render()

    assert "motor speed" in text
    assert "coarse" in text


def test_a_capture_with_no_pulse_is_refused() -> None:
    with pytest.raises(ValueError, match="no interval"):
        advise(())


def test_the_report_carries_the_measurements_behind_it() -> None:
    result = advise(_capture(rate=NOMINAL_BIT_RATE_HZ * 1.04))

    assert result.speed.error == pytest.approx(0.04, abs=0.01)
    assert result.stability.samples == 6_000
