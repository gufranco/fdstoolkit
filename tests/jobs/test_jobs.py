from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import pytest
from pydantic import BaseModel

from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError
from fdstoolkit.ui.jobs import (
    Controls,
    JobBoard,
    JobBusyError,
    JobState,
    NotStoppableError,
    NotWaitingError,
)

SETTLE = 2.0
BRIEF = 0.05


class Answer(BaseModel):
    value: int


def answering(value: int) -> Callable[[Controls], Answer]:
    def work(controls: Controls) -> Answer:
        del controls
        return Answer(value=value)

    return work


def finished(board: JobBoard, job_id: str) -> JobState:
    assert board.wait(job_id, SETTLE)
    job = board.get(job_id)
    assert job is not None
    return job.state


def test_a_job_that_succeeds_carries_its_result() -> None:
    # Arrange
    board = JobBoard()

    # Act
    job = board.start("dump", writes=False, work=answering(7))

    # Assert
    assert finished(board, job.id) is JobState.DONE
    done = board.get(job.id)
    assert done is not None
    assert done.result == {"value": 7}
    assert done.error == ""


def test_a_job_records_every_step_it_reports() -> None:
    # Arrange
    board = JobBoard()

    def work(controls: Controls) -> Answer:
        controls.step("reading side 0")
        controls.step("reading side 1")
        return Answer(value=1)

    job = board.start("dump", writes=False, work=work)
    finished(board, job.id)

    # Act
    done = board.get(job.id)

    # Assert
    assert done is not None
    assert done.steps == ("reading side 0", "reading side 1")


def test_a_hardware_fault_fails_the_job_with_its_message() -> None:
    # Arrange
    board = JobBoard()

    def work(controls: Controls) -> Answer:
        del controls
        message = "the device stopped answering"
        raise HardwareFaultError(message, kind=FaultKind.LINK)

    # Act
    job = board.start("write", writes=True, work=work)

    # Assert
    assert finished(board, job.id) is JobState.FAILED
    failed = board.get(job.id)
    assert failed is not None
    assert failed.error == "the device stopped answering"


def test_an_unexpected_error_still_fails_the_job_and_says_so() -> None:
    # Arrange
    board = JobBoard()

    def work(controls: Controls) -> Answer:
        del controls
        message = "unexpected"
        raise RuntimeError(message)

    # Act
    job = board.start("dump", writes=False, work=work)

    # Assert
    assert finished(board, job.id) is JobState.FAILED
    failed = board.get(job.id)
    assert failed is not None
    assert "stopped unexpectedly: unexpected" in failed.error


def test_a_job_waits_for_the_disk_to_be_turned_over() -> None:
    # Arrange
    board = JobBoard()
    answered: list[bool] = []

    def work(controls: Controls) -> Answer:
        answered.append(controls.ask("turn the disk over"))
        return Answer(value=2)

    job = board.start("dump", writes=False, work=work)
    reached = board.wait_for_state(job.id, JobState.WAITING, SETTLE)
    waiting = board.get(job.id)

    # Act
    board.answer(job.id, yes=True)

    # Assert
    assert reached
    assert waiting is not None
    assert waiting.prompt == "turn the disk over"
    assert finished(board, job.id) is JobState.DONE
    assert answered == [True]


def test_a_declined_turn_reaches_the_job_as_a_no() -> None:
    # Arrange
    board = JobBoard()
    answered: list[bool] = []

    def work(controls: Controls) -> Answer:
        answered.append(controls.ask("turn the disk over"))
        return Answer(value=3)

    job = board.start("dump", writes=False, work=work)
    board.wait_for_state(job.id, JobState.WAITING, SETTLE)
    board.answer(job.id, yes=False)

    # Act
    finished(board, job.id)

    # Assert
    assert answered == [False]


def test_a_turn_nobody_answers_is_taken_as_a_no() -> None:
    # Arrange
    board = JobBoard(answer_limit=BRIEF)
    answered: list[bool] = []

    def work(controls: Controls) -> Answer:
        answered.append(controls.ask("turn the disk over"))
        return Answer(value=4)

    job = board.start("dump", writes=False, work=work)
    finished(board, job.id)

    # Act
    done = board.get(job.id)

    # Assert
    assert done is not None
    assert answered == [False]
    assert any("no answer" in step for step in done.steps)


def test_only_one_disk_job_runs_at_a_time() -> None:
    # Arrange
    board = JobBoard()
    gate = threading.Event()

    def work(controls: Controls) -> Answer:
        del controls
        gate.wait(SETTLE)
        return Answer(value=5)

    first = board.start("dump", writes=False, work=work)

    # Act
    with pytest.raises(JobBusyError, match="dump is already running") as raised:
        board.start("write", writes=True, work=work)

    # Assert
    assert raised.type is JobBusyError
    gate.set()
    assert finished(board, first.id) is JobState.DONE


def test_a_finished_job_frees_the_board() -> None:
    # Arrange
    board = JobBoard()
    first = board.start("dump", writes=False, work=answering(6))
    finished(board, first.id)

    # Act
    second = board.start("dump", writes=False, work=answering(6))

    # Assert
    assert second.id != first.id
    assert finished(board, second.id) is JobState.DONE


def test_the_current_job_is_the_one_still_running() -> None:
    # Arrange
    board = JobBoard()
    gate = threading.Event()

    def work(controls: Controls) -> Answer:
        del controls
        gate.wait(SETTLE)
        return Answer(value=8)

    job = board.start("surface", writes=True, work=work)

    # Act
    current = board.current()

    # Assert
    assert current is not None
    assert current.id == job.id
    assert current.writes
    gate.set()
    finished(board, job.id)
    assert board.current() is None


def test_answering_a_job_that_is_not_waiting_is_refused() -> None:
    # Arrange
    board = JobBoard()
    job = board.start("dump", writes=False, work=answering(9))
    finished(board, job.id)

    # Act
    with pytest.raises(NotWaitingError) as raised:
        board.answer(job.id, yes=True)

    # Assert
    assert raised.type is NotWaitingError


def test_an_unknown_job_is_not_found() -> None:
    # Arrange
    board = JobBoard()
    assert board.get("nothing") is None
    assert not board.wait("nothing", BRIEF)
    assert not board.wait_for_state("nothing", JobState.DONE, BRIEF)

    # Act
    with pytest.raises(NotWaitingError) as raised:
        board.answer("nothing", yes=True)

    # Assert
    assert raised.type is NotWaitingError


def test_a_stoppable_job_sees_the_stop_between_steps() -> None:
    # Arrange
    board = JobBoard()
    gate = threading.Event()
    seen: list[bool] = []

    def work(controls: Controls) -> Answer:
        seen.append(controls.stopped())
        gate.wait(SETTLE)
        seen.append(controls.stopped())
        return Answer(value=10)

    job = board.start("calibrate", writes=False, work=work, stoppable=True)

    # Act
    board.stop(job.id)

    # Assert
    gate.set()
    assert finished(board, job.id) is JobState.DONE
    assert seen[-1] is True
    stopped = board.get(job.id)
    assert stopped is not None
    assert stopped.stoppable
    assert stopped.stopping


def test_a_job_that_is_not_stoppable_refuses_a_stop() -> None:
    # Arrange
    board = JobBoard()
    gate = threading.Event()

    def work(controls: Controls) -> Answer:
        del controls
        gate.wait(SETTLE)
        return Answer(value=11)

    job = board.start("write", writes=True, work=work)

    # Act
    with pytest.raises(NotStoppableError) as raised:
        board.stop(job.id)

    # Assert
    assert raised.type is NotStoppableError
    gate.set()
    finished(board, job.id)
    with pytest.raises(NotStoppableError):
        board.stop("nothing")


def test_a_hardware_fault_is_logged_with_its_job_and_command(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    board = JobBoard()

    def work(controls: Controls) -> Answer:
        del controls
        message = "the device stopped answering"
        raise HardwareFaultError(message, kind=FaultKind.LINK)

    # Act
    with caplog.at_level(logging.WARNING, logger="fdstoolkit.ui.jobs"):
        job = board.start("write", writes=True, work=work)
        finished(board, job.id)

    # Assert
    assert any(
        job.id in record.getMessage()
        and "write" in record.getMessage()
        and "the device stopped answering" in record.getMessage()
        for record in caplog.records
    )


def test_every_step_is_logged_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    # Arrange
    board = JobBoard()

    def work(controls: Controls) -> Answer:
        controls.step("reading side 0")
        return Answer(value=1)

    # Act
    with caplog.at_level(logging.DEBUG, logger="fdstoolkit.ui.jobs"):
        job = board.start("dump", writes=False, work=work)
        finished(board, job.id)

    # Assert
    assert any("reading side 0" in record.getMessage() for record in caplog.records)


def test_shutting_down_with_nothing_running_returns_nothing() -> None:
    # Arrange
    board = JobBoard()

    # Act
    left = board.shutdown(BRIEF)

    # Assert
    assert left is None


def test_shutting_down_asks_a_running_job_to_stop_and_returns_it() -> None:
    # Arrange
    board = JobBoard()
    release = threading.Event()

    def work(controls: Controls) -> Answer:
        release.wait(SETTLE)
        del controls
        return Answer(value=1)

    job = board.start("write", writes=True, work=work, stoppable=True)
    left = board.shutdown(BRIEF)

    # Act
    release.set()

    # Assert
    assert left is not None
    assert left.id == job.id
    assert left.stopping


def test_shutting_down_waits_for_a_job_that_ends_in_time() -> None:
    # Arrange
    board = JobBoard()
    board.start("dump", writes=False, work=answering(1))

    # Act
    left = board.shutdown(SETTLE)

    # Assert
    assert left is None


def refuse_to_start(self: threading.Thread) -> None:
    del self
    message = "can't start new thread"
    raise RuntimeError(message)


def test_a_job_whose_thread_cannot_start_frees_the_board(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    board = JobBoard()
    monkeypatch.setattr(threading.Thread, "start", refuse_to_start)

    # Act
    with pytest.raises(RuntimeError, match="can't start new thread") as raised:
        board.start("dump", writes=False, work=answering(1))

    # Assert
    assert raised.type is RuntimeError
    assert board.current() is None
