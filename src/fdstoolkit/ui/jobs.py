from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from fdstoolkit.hardware.ports import HardwareFaultError
from fdstoolkit.hardware.session import SideFlipError, WriteRefusedError
from fdstoolkit.quality.surface import SurfaceTestRefusedError

if TYPE_CHECKING:
    from pydantic import BaseModel

ANSWER_LIMIT_S: Final = 600.0
HISTORY: Final = 20
FAULTS: Final = (HardwareFaultError, WriteRefusedError, SideFlipError, SurfaceTestRefusedError)

logger = logging.getLogger(__name__)


class JobState(StrEnum):
    RUNNING = "running"
    WAITING = "waiting"
    DONE = "done"
    FAILED = "failed"


ACTIVE: Final = frozenset({JobState.RUNNING, JobState.WAITING})


class JobBusyError(Exception):
    pass


class NotWaitingError(Exception):
    pass


class NotStoppableError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    command: str
    writes: bool
    stoppable: bool = False
    stopping: bool = False
    state: JobState = JobState.RUNNING
    steps: tuple[str, ...] = ()
    prompt: str = ""
    result: dict[str, Any] | None = None
    error: str = ""
    kept: dict[str, Any] | None = None


class Controls:
    def __init__(self, board: JobBoard, job_id: str) -> None:
        self._board = board
        self._job_id = job_id

    def step(self, message: str) -> None:
        self._board.step(self._job_id, message)

    def ask(self, prompt: str) -> bool:
        return self._board.ask(self._job_id, prompt)

    def stopped(self) -> bool:
        return self._board.stopping(self._job_id)

    def keep(self, file: dict[str, Any]) -> None:
        self._board.keep(self._job_id, file)


class JobBoard:
    def __init__(self, *, answer_limit: float = ANSWER_LIMIT_S) -> None:
        self._changed = threading.Condition()
        self._jobs: dict[str, Job] = {}
        self._replies: dict[str, bool] = {}
        self._answer_limit = answer_limit

    def start(
        self,
        command: str,
        *,
        writes: bool,
        work: Callable[[Controls], BaseModel],
        stoppable: bool = False,
    ) -> Job:
        with self._changed:
            running = self._active()
            if running is not None:
                message = f"{running.command} is already running, so the drive is busy"
                raise JobBusyError(message)
            job = Job(id=uuid.uuid4().hex, command=command, writes=writes, stoppable=stoppable)
            self._jobs = self._trimmed() | {job.id: job}
        threading.Thread(
            target=self._run, args=(job.id, work), name=f"fdstoolkit-{command}", daemon=True
        ).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._changed:
            return self._jobs.get(job_id)

    def current(self) -> Job | None:
        with self._changed:
            return self._active()

    def wait(self, job_id: str, timeout: float) -> bool:
        with self._changed:
            return self._changed.wait_for(
                lambda: self._state_of(job_id) in {JobState.DONE, JobState.FAILED}, timeout
            )

    def wait_for_state(self, job_id: str, state: JobState, timeout: float) -> bool:
        with self._changed:
            return self._changed.wait_for(lambda: self._state_of(job_id) is state, timeout)

    def step(self, job_id: str, message: str) -> None:
        with self._changed:
            job = self._jobs[job_id]
            self._put(replace(job, steps=(*job.steps, message)))

    def ask(self, job_id: str, prompt: str) -> bool:
        with self._changed:
            self._put(replace(self._jobs[job_id], state=JobState.WAITING, prompt=prompt))
            answered = self._changed.wait_for(lambda: job_id in self._replies, self._answer_limit)
            reply = self._replies.pop(job_id, False)
            job = self._jobs[job_id]
            steps = job.steps
            if not answered:
                minutes = self._answer_limit / 60
                steps = (*steps, f"no answer within {minutes:g} minute(s), taken as no")
            self._put(replace(job, state=JobState.RUNNING, prompt="", steps=steps))
            return reply

    def answer(self, job_id: str, *, yes: bool) -> None:
        with self._changed:
            job = self._jobs.get(job_id)
            if job is None or job.state is not JobState.WAITING:
                message = "that job is not waiting for an answer"
                raise NotWaitingError(message)
            self._replies = self._replies | {job_id: yes}
            self._changed.notify_all()

    def keep(self, job_id: str, file: dict[str, Any]) -> None:
        with self._changed:
            self._put(replace(self._jobs[job_id], kept=file))

    def stop(self, job_id: str) -> None:
        with self._changed:
            job = self._jobs.get(job_id)
            if job is None or not job.stoppable or job.state not in ACTIVE:
                message = "that job cannot be stopped"
                raise NotStoppableError(message)
            self._put(replace(job, stopping=True))

    def stopping(self, job_id: str) -> bool:
        with self._changed:
            return self._jobs[job_id].stopping

    def _run(self, job_id: str, work: Callable[[Controls], BaseModel]) -> None:
        try:
            result = work(Controls(self, job_id))
        except FAULTS as error:
            self._end(job_id, state=JobState.FAILED, error=str(error))
        except Exception as error:
            logger.exception("disk job %s stopped unexpectedly", job_id)
            self._end(job_id, state=JobState.FAILED, error=f"the job stopped unexpectedly: {error}")
        else:
            self._end(job_id, state=JobState.DONE, result=result.model_dump())

    def _end(
        self,
        job_id: str,
        *,
        state: JobState,
        error: str = "",
        result: dict[str, Any] | None = None,
    ) -> None:
        with self._changed:
            job = self._jobs[job_id]
            self._put(replace(job, state=state, error=error, result=result, prompt=""))

    def _put(self, job: Job) -> None:
        self._jobs = self._jobs | {job.id: job}
        self._changed.notify_all()

    def _active(self) -> Job | None:
        return next((job for job in self._jobs.values() if job.state in ACTIVE), None)

    def _state_of(self, job_id: str) -> JobState | None:
        job = self._jobs.get(job_id)
        return None if job is None else job.state

    def _trimmed(self) -> dict[str, Job]:
        kept = list(self._jobs.items())[-(HISTORY - 1) :]
        return dict(kept)
