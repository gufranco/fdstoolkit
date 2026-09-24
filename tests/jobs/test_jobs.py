from __future__ import annotations

import threading
from collections.abc import Callable

import pytest
from pydantic import BaseModel

from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError
from fdstoolkit.ui.jobs import Controls, JobBoard, JobBusyError, JobState, NotWaitingError

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
    board = JobBoard()

    job = board.start("dump", writes=False, work=answering(7))

    assert finished(board, job.id) is JobState.DONE
    done = board.get(job.id)
    assert done is not None
    assert done.result == {"value": 7}
    assert done.error == ""


def test_a_job_records_every_step_it_reports() -> None:
    board = JobBoard()

    def work(controls: Controls) -> Answer:
        controls.step("reading side 0")
        controls.step("reading side 1")
        return Answer(value=1)

    job = board.start("dump", writes=False, work=work)

    finished(board, job.id)
    done = board.get(job.id)
    assert done is not None
    assert done.steps == ("reading side 0", "reading side 1")


def test_a_hardware_fault_fails_the_job_with_its_message() -> None:
    board = JobBoard()

    def work(controls: Controls) -> Answer:
        del controls
        message = "the device stopped answering"
        raise HardwareFaultError(message, kind=FaultKind.LINK)

    job = board.start("write", writes=True, work=work)

    assert finished(board, job.id) is JobState.FAILED
    failed = board.get(job.id)
    assert failed is not None
    assert failed.error == "the device stopped answering"


def test_an_unexpected_error_still_fails_the_job_and_says_so() -> None:
    board = JobBoard()

    def work(controls: Controls) -> Answer:
        del controls
        message = "unexpected"
        raise RuntimeError(message)

    job = board.start("dump", writes=False, work=work)

    assert finished(board, job.id) is JobState.FAILED
    failed = board.get(job.id)
    assert failed is not None
    assert "stopped unexpectedly: unexpected" in failed.error


def test_a_job_waits_for_the_disk_to_be_turned_over() -> None:
    board = JobBoard()
    answered: list[bool] = []

    def work(controls: Controls) -> Answer:
        answered.append(controls.ask("turn the disk over"))
        return Answer(value=2)

    job = board.start("dump", writes=False, work=work)

    assert board.wait_for_state(job.id, JobState.WAITING, SETTLE)
    waiting = board.get(job.id)
    assert waiting is not None
    assert waiting.prompt == "turn the disk over"
    board.answer(job.id, yes=True)
    assert finished(board, job.id) is JobState.DONE
    assert answered == [True]


def test_a_declined_turn_reaches_the_job_as_a_no() -> None:
    board = JobBoard()
    answered: list[bool] = []

    def work(controls: Controls) -> Answer:
        answered.append(controls.ask("turn the disk over"))
        return Answer(value=3)

    job = board.start("dump", writes=False, work=work)

    board.wait_for_state(job.id, JobState.WAITING, SETTLE)
    board.answer(job.id, yes=False)
    finished(board, job.id)
    assert answered == [False]


def test_a_turn_nobody_answers_is_taken_as_a_no() -> None:
    board = JobBoard(answer_limit=BRIEF)
    answered: list[bool] = []

    def work(controls: Controls) -> Answer:
        answered.append(controls.ask("turn the disk over"))
        return Answer(value=4)

    job = board.start("dump", writes=False, work=work)

    finished(board, job.id)
    done = board.get(job.id)
    assert done is not None
    assert answered == [False]
    assert any("no answer" in step for step in done.steps)


def test_only_one_disk_job_runs_at_a_time() -> None:
    board = JobBoard()
    gate = threading.Event()

    def work(controls: Controls) -> Answer:
        del controls
        gate.wait(SETTLE)
        return Answer(value=5)

    first = board.start("dump", writes=False, work=work)

    with pytest.raises(JobBusyError, match="dump is already running"):
        board.start("write", writes=True, work=work)
    gate.set()
    finished(board, first.id)


def test_a_finished_job_frees_the_board() -> None:
    board = JobBoard()
    first = board.start("dump", writes=False, work=answering(6))
    finished(board, first.id)

    second = board.start("dump", writes=False, work=answering(6))

    assert second.id != first.id
    finished(board, second.id)


def test_the_current_job_is_the_one_still_running() -> None:
    board = JobBoard()
    gate = threading.Event()

    def work(controls: Controls) -> Answer:
        del controls
        gate.wait(SETTLE)
        return Answer(value=8)

    job = board.start("surface", writes=True, work=work)

    current = board.current()
    assert current is not None
    assert current.id == job.id
    assert current.writes
    gate.set()
    finished(board, job.id)
    assert board.current() is None


def test_answering_a_job_that_is_not_waiting_is_refused() -> None:
    board = JobBoard()
    job = board.start("dump", writes=False, work=answering(9))
    finished(board, job.id)

    with pytest.raises(NotWaitingError):
        board.answer(job.id, yes=True)


def test_an_unknown_job_is_not_found() -> None:
    board = JobBoard()

    assert board.get("nothing") is None
    assert not board.wait("nothing", BRIEF)
    assert not board.wait_for_state("nothing", JobState.DONE, BRIEF)
    with pytest.raises(NotWaitingError):
        board.answer("nothing", yes=True)
