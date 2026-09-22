from __future__ import annotations

import pytest

from fdstk.hardware.deadline import Deadline, DeadlineExceededError, guard
from fdstk.hardware.ports import FaultKind, HardwareFaultError


def test_a_deadline_that_has_not_passed_is_alive() -> None:
    clock = iter([0.0, 0.5])
    deadline = Deadline(seconds=1.0, now=lambda: next(clock))

    assert not deadline.expired


def test_a_deadline_that_has_passed_is_expired() -> None:
    clock = iter([0.0, 2.0])
    deadline = Deadline(seconds=1.0, now=lambda: next(clock))

    assert deadline.expired


def test_a_deadline_reports_what_is_left() -> None:
    clock = iter([0.0, 0.25])
    deadline = Deadline(seconds=1.0, now=lambda: next(clock))

    assert deadline.remaining == pytest.approx(0.75)


def test_remaining_never_goes_negative() -> None:
    clock = iter([0.0, 5.0])
    deadline = Deadline(seconds=1.0, now=lambda: next(clock))

    assert deadline.remaining == 0.0


def test_a_call_within_the_deadline_returns_its_value() -> None:
    clock = iter([0.0, 0.1])
    deadline = Deadline(seconds=1.0, now=lambda: next(clock))

    assert guard(deadline, "read a block", lambda: 42) == 42


def test_a_call_that_overruns_is_a_timeout_fault() -> None:
    clock = iter([0.0, 9.0])
    deadline = Deadline(seconds=1.0, now=lambda: next(clock))

    with pytest.raises(HardwareFaultError) as caught:
        guard(deadline, "read a block", lambda: 42)

    assert caught.value.kind is FaultKind.TIMEOUT
    assert "read a block" in str(caught.value)


def test_the_timeout_names_how_long_it_waited() -> None:
    clock = iter([0.0, 3.0])
    deadline = Deadline(seconds=1.5, now=lambda: next(clock))

    with pytest.raises(HardwareFaultError, match=r"1\.5"):
        guard(deadline, "seek", lambda: None)


def test_a_deadline_error_is_a_hardware_fault() -> None:
    assert issubclass(DeadlineExceededError, HardwareFaultError)


def test_a_deadline_of_zero_is_refused() -> None:
    with pytest.raises(ValueError, match="positive"):
        Deadline(seconds=0.0)


def test_a_deadline_uses_a_real_clock_by_default() -> None:
    deadline = Deadline(seconds=60.0)

    assert deadline.remaining > 0
