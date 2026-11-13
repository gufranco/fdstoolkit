from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest

from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError
from fdstoolkit.hardware.watchdog import (
    MEASURED_FLOOR_S,
    MEASURED_MULTIPLE,
    UNMEASURED_CEILING_S,
    StallError,
    Watchdog,
)

BRIEF = 0.05


class Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


UNPLUGGED = "unplugged"
READ_ERROR = "read error"


def nothing() -> None:
    return None


def unplug() -> None:
    raise HardwareFaultError(UNPLUGGED, kind=FaultKind.LINK)


def broken() -> bytes:
    raise OSError(READ_ERROR)


def fail_during_side(watchdog: Watchdog, clock: Clock) -> None:
    with watchdog.side("reading side 0"):
        clock.value += 1.0
        unplug()


def call_after_the_deadline(watchdog: Watchdog, clock: Clock, action: threading.Event) -> None:
    with watchdog.side("writing side 0"):
        clock.value += UNMEASURED_CEILING_S
        watchdog.call(action.set)


@pytest.fixture(name="gate")
def gate_fixture() -> Iterator[threading.Event]:
    gate = threading.Event()
    yield gate
    gate.set()


def test_the_limit_before_any_side_is_measured_is_the_ceiling() -> None:
    # Arrange
    watchdog = Watchdog(on_stall=nothing)

    # Act
    limit = watchdog.limit

    # Assert
    assert limit == UNMEASURED_CEILING_S
    assert watchdog.measured is None


def test_a_measured_side_sets_the_limit_to_a_multiple_of_its_duration() -> None:
    # Arrange
    clock = Clock()
    watchdog = Watchdog(on_stall=nothing, now=clock)

    # Act
    with watchdog.side("reading side 0"):
        clock.value += 6.0

    # Assert
    assert watchdog.measured == pytest.approx(6.0)
    assert watchdog.limit == pytest.approx(6.0 * MEASURED_MULTIPLE)


def test_a_very_quick_side_still_leaves_the_floor() -> None:
    # Arrange
    clock = Clock()
    watchdog = Watchdog(on_stall=nothing, now=clock)

    # Act
    with watchdog.side("reading side 0"):
        clock.value += 0.1

    # Assert
    assert watchdog.limit == MEASURED_FLOOR_S


def test_a_slow_measured_side_never_raises_the_limit_past_the_ceiling() -> None:
    # Arrange
    clock = Clock()
    watchdog = Watchdog(on_stall=nothing, now=clock)

    # Act
    with watchdog.side("reading side 0"):
        clock.value += 15.0

    # Assert
    assert watchdog.limit == UNMEASURED_CEILING_S


def test_a_side_that_fails_leaves_the_measurement_alone() -> None:
    # Arrange
    clock = Clock()
    watchdog = Watchdog(on_stall=nothing, now=clock)

    # Act
    with pytest.raises(HardwareFaultError, match=UNPLUGGED) as raised:
        fail_during_side(watchdog, clock)

    # Assert
    assert raised.type is HardwareFaultError
    assert watchdog.measured is None


def test_a_call_outside_a_side_runs_directly() -> None:
    # Arrange
    watchdog = Watchdog(on_stall=nothing)

    # Act
    value = watchdog.call(lambda: 7)

    # Assert
    assert value == 7


def test_a_call_inside_a_side_returns_its_value() -> None:
    # Arrange
    watchdog = Watchdog(on_stall=nothing)

    # Act
    with watchdog.side("reading side 0"):
        value = watchdog.call(lambda: b"chunk")

    # Assert
    assert value == b"chunk"


def test_an_error_raised_by_the_call_reaches_the_caller() -> None:
    # Arrange
    watchdog = Watchdog(on_stall=nothing)

    # Act
    with pytest.raises(OSError, match=READ_ERROR) as raised, watchdog.side("reading side 0"):
        watchdog.call(broken)

    # Assert
    assert raised.type is OSError


def test_a_call_that_never_returns_is_a_stall(gate: threading.Event) -> None:
    # Arrange
    closed = threading.Event()
    watchdog = Watchdog(on_stall=closed.set, ceiling=BRIEF)

    # Act
    with pytest.raises(StallError) as caught, watchdog.side("reading side 0"):
        watchdog.call(gate.wait)

    # Assert
    assert caught.value.kind is FaultKind.TIMEOUT
    assert "reading side 0 did not finish within 0.1 seconds" in str(caught.value)
    assert closed.wait(1.0)


def test_a_call_made_after_the_deadline_passed_does_not_run() -> None:
    # Arrange
    clock = Clock()
    ran = threading.Event()
    watchdog = Watchdog(on_stall=nothing, now=clock)

    # Act
    with pytest.raises(StallError) as raised:
        call_after_the_deadline(watchdog, clock, ran)

    # Assert
    assert raised.type is StallError
    assert not ran.is_set()


def test_a_stall_is_a_hardware_fault_that_names_what_stalled() -> None:
    # Arrange
    what = "reading side 1"
    seconds = 18.0

    # Act
    error = StallError(what, seconds)

    # Assert
    assert isinstance(error, HardwareFaultError)
    assert "reading side 1 did not finish within 18.0 seconds" in str(error)
    assert "nothing was retried" in str(error)
    assert "half written" not in str(error)


def test_a_stall_while_writing_warns_the_side_may_be_half_written() -> None:
    # Arrange
    what = "writing side 0"
    seconds = 18.0
    writing = True

    # Act
    error = StallError(what, seconds, writing=writing)

    # Assert
    assert "half written, so dump the disk before using it" in str(error)


@pytest.mark.parametrize(
    ("ceiling", "multiple", "floor"),
    [(0.0, 3.0, 2.0), (20.0, 0.0, 2.0), (20.0, 3.0, 0.0)],
)
def test_a_limit_that_is_not_positive_is_refused(
    ceiling: float, multiple: float, floor: float
) -> None:
    # Arrange
    on_stall = nothing

    # Act
    with pytest.raises(ValueError, match="positive") as raised:
        Watchdog(on_stall=on_stall, ceiling=ceiling, multiple=multiple, floor=floor)

    # Assert
    assert raised.type is ValueError


def test_a_quick_side_after_a_slow_one_keeps_the_slow_limit() -> None:
    # Arrange
    clock = Clock()
    watchdog = Watchdog(on_stall=nothing, now=clock)

    # Act
    for seconds in (6.0, 0.1):
        with watchdog.side("reading side 0"):
            clock.value += seconds

    # Assert
    assert watchdog.measured == pytest.approx(6.0)
    assert watchdog.limit == pytest.approx(6.0 * MEASURED_MULTIPLE)


def test_only_the_recent_sides_set_the_limit() -> None:
    # Arrange
    clock = Clock()
    watchdog = Watchdog(on_stall=nothing, now=clock)

    # Act
    for seconds in (6.0, 1.0, 1.0, 1.0, 1.0):
        with watchdog.side("reading side 0"):
            clock.value += seconds

    # Assert
    assert watchdog.measured == pytest.approx(1.0)
