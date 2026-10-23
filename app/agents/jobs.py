"""성적표 백그라운드 작업 큐: 작업자 스레드 1개가 1개씩 실행하고 나머지는 대기한다."""

from __future__ import annotations

import dataclasses
import logging
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.agents.models import Agent
from app.agents.questions import ScoreQuestion, make_questions
from app.agents.runtime import AgentRuntime
from app.agents.scorecard import run_scorecard
from app.agents.store import AgentNotFound

log = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "done", "failed"]
SHUTDOWN_JOIN_S = 5.0
INTERNAL_MESSAGE = "성적표를 만드는 중 오류가 났습니다."
EXPIRED_MESSAGE = "상담원이 만료되어 성적표를 만들지 않았습니다."


class JobBusy(RuntimeError): ...


class JobRunning(RuntimeError):
    def __init__(self, job_id: str) -> None:
        super().__init__(job_id)
        self.job_id = job_id


@dataclass
class Job:
    job_id: str
    agent_id: str
    status: JobStatus
    done: int
    total: int
    report: dict[str, Any] | None
    error: dict[str, str] | None
    created_at: float


@dataclass
class _Work:
    job: Job
    agent: Agent
    questions: list[ScoreQuestion]
    voice: bool


class ScorecardJobs:
    def __init__(self, rt: AgentRuntime, max_waiting: int = 4,
                 run: Callable[..., dict[str, Any]] = run_scorecard,
                 ttl_s: float = 86400.0, clock: Callable[[], float] = time.time) -> None:
        self._rt = rt
        self._max_waiting = max_waiting
        self._run = run
        self._ttl_s = ttl_s
        self._clock = clock
        self._cond = threading.Condition()
        self._jobs: dict[str, Job] = {}
        self._queue: deque[_Work] = deque()
        self._stopping = False
        self._thread = threading.Thread(target=self._loop, name="scorecard-jobs", daemon=True)
        self._thread.start()

    def submit(self, agent: Agent, n: int, voice: bool) -> Job:
        questions = make_questions(agent, n)
        steps = 2 if voice and self._rt.voice_capable else 1
        with self._cond:
            if self._stopping:
                raise JobBusy("작업 큐가 멈췄습니다")
            self._purge_locked()
            active = [j for j in self._jobs.values() if j.status in ("queued", "running")]
            for j in active:
                if j.agent_id == agent.agent_id:
                    raise JobRunning(j.job_id)
            if len(active) > self._max_waiting:  # 실행 1개 + 대기 max_waiting개
                raise JobBusy("성적표 대기열이 가득 찼습니다")
            job_id = "sc_" + secrets.token_hex(6)
            while job_id in self._jobs:
                job_id = "sc_" + secrets.token_hex(6)
            job = Job(job_id=job_id, agent_id=agent.agent_id, status="queued", done=0,
                      total=len(questions) * steps, report=None, error=None,
                      created_at=self._clock())
            self._jobs[job_id] = job
            self._queue.append(_Work(job, agent, questions, voice))
            self._cond.notify_all()
            return dataclasses.replace(job)

    def get(self, job_id: str) -> Job:
        with self._cond:
            self._purge_locked()
            return dataclasses.replace(self._jobs[job_id])

    def position(self, job_id: str) -> int:
        with self._cond:
            for i, w in enumerate(self._queue, start=1):
                if w.job.job_id == job_id:
                    return i
            return 0

    def shutdown(self) -> None:
        with self._cond:
            self._stopping = True
            self._cond.notify_all()
        self._thread.join(timeout=SHUTDOWN_JOIN_S)

    def _agent_live(self, agent_id: str) -> bool:
        # store.get 은 만료 agent 를 바로 지우므로 sweep 결과가 아니라 get 으로 확인한다
        try:
            self._rt.store.get(agent_id)
        except AgentNotFound:
            return False
        return True

    def _purge_locked(self) -> None:
        now = self._clock()
        for job_id, j in list(self._jobs.items()):
            if j.status in ("queued", "running"):
                continue
            if now >= j.created_at + self._ttl_s or not self._agent_live(j.agent_id):
                del self._jobs[job_id]

    def _loop(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._stopping or bool(self._queue))
                if self._stopping:
                    return
                work = self._queue.popleft()
                job = work.job
                if not self._agent_live(job.agent_id):
                    job.status = "failed"
                    job.error = {"code": "internal", "message": EXPIRED_MESSAGE}
                    continue
                job.status = "running"
            self._execute(work)

    def _execute(self, work: _Work) -> None:
        job = work.job

        def progress(done: int, total: int) -> None:
            with self._cond:
                job.done = done
                job.total = total

        try:
            report = self._run(self._rt, work.agent, work.questions, voice=work.voice,
                               progress=progress)
        except Exception:
            log.exception("scorecard job %s failed", job.job_id)
            with self._cond:
                job.status = "failed"
                job.error = {"code": "internal", "message": INTERNAL_MESSAGE}
            return
        with self._cond:
            job.report = report
            job.done = job.total
            job.status = "done"
