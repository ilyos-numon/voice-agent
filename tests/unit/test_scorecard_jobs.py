import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from app.agents.jobs import JobBusy, JobRunning, ScorecardJobs
from app.agents.models import Agent, AgentSettings, Chunk
from app.agents.questions import ScoreQuestion
from app.agents.runtime import AgentRuntime, build_agent_runtime
from app.config import Settings
from app.pipeline.stubs import PassthroughSTT, SilentTTS

CHUNKS = (
    Chunk("q-001", "주차 가능한가요?", "지하 1층에 주차장이 있습니다.", "주차 가능한가요?", "faq_csv"),
    Chunk("q-002", "영업 시간은 언제인가요?", "평일 9시부터 6시까지입니다.", "영업 시간은 언제인가요?",
          "faq_csv"),
)
WAIT_S = 5.0


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeRun:
    """호출마다 started 를 알리고 release 가 열릴 때까지 막는다 (sleep 없이 Event 로 동기화)."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.started: list[threading.Event] = [threading.Event() for _ in range(8)]
        self.progressed = threading.Event()
        self.release = threading.Event()
        self.calls: list[tuple[str, int, bool]] = []

    def __call__(self, rt: AgentRuntime, agent: Agent, questions: list[ScoreQuestion], *,
                 voice: bool, progress: Callable[[int, int], None]) -> dict[str, Any]:
        self.started[len(self.calls)].set()
        self.calls.append((agent.agent_id, len(questions), voice))
        progress(1, len(questions))
        self.progressed.set()
        assert self.release.wait(WAIT_S)
        if self.fail:
            raise RuntimeError("boom with secret question text")
        return {"agent_id": agent.agent_id, "ok": True}


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def rt(tmp_path: Path, clock: Clock) -> AgentRuntime:
    settings = Settings(_env_file=None, presets_dir=tmp_path, llm_backend="stub")  # type: ignore[call-arg]
    return build_agent_runtime(settings, PassthroughSTT(), SilentTTS(), clock=clock)


@pytest.fixture
def make_jobs(rt: AgentRuntime, clock: Clock) -> Iterator[Callable[..., ScorecardJobs]]:
    made: list[tuple[ScorecardJobs, FakeRun]] = []

    def make(run: FakeRun, ttl_s: float = 86400.0) -> ScorecardJobs:
        jobs = ScorecardJobs(rt, run=run, ttl_s=ttl_s, clock=clock)
        made.append((jobs, run))
        return jobs

    yield make
    for jobs, run in made:
        run.release.set()
        jobs.shutdown()


def _agent(rt: AgentRuntime) -> Agent:
    return rt.store.create("테스트", AgentSettings(), CHUNKS)


def test_queued_running_done(rt: AgentRuntime, make_jobs: Callable[[FakeRun], ScorecardJobs]) -> None:
    run = FakeRun()
    jobs = make_jobs(run)
    agent = _agent(rt)
    job = jobs.submit(agent, 2, voice=False)
    assert job.job_id.startswith("sc_") and len(job.job_id) == 15
    assert job.status == "queued"
    assert job.agent_id == agent.agent_id
    assert (job.done, job.total) == (0, 2)
    assert job.report is None and job.error is None

    assert run.started[0].wait(WAIT_S)
    assert run.progressed.wait(WAIT_S)
    cur = jobs.get(job.job_id)
    assert cur.status == "running"
    assert (cur.done, cur.total) == (1, 2)
    assert jobs.position(job.job_id) == 0

    run.release.set()
    jobs.shutdown()  # 실행 중인 작업을 마친 뒤 스레드가 끝난다
    done = jobs.get(job.job_id)
    assert done.status == "done"
    assert done.report == {"agent_id": agent.agent_id, "ok": True}
    assert done.done == done.total == 2
    assert jobs.position(job.job_id) == 0
    assert run.calls == [(agent.agent_id, 2, False)]


def test_voice_total_uses_capability(rt: AgentRuntime,
                                     make_jobs: Callable[[FakeRun], ScorecardJobs]) -> None:
    run = FakeRun()
    jobs = make_jobs(run)
    job = jobs.submit(_agent(rt), 2, voice=True)
    assert job.total == 2  # 스텁 STT/TTS 는 음성 채널이 없어 질문 수 × 1


def test_same_agent_running(rt: AgentRuntime, make_jobs: Callable[[FakeRun], ScorecardJobs]) -> None:
    run = FakeRun()
    jobs = make_jobs(run)
    a, b = _agent(rt), _agent(rt)
    first = jobs.submit(a, 2, voice=False)
    assert run.started[0].wait(WAIT_S)
    queued = jobs.submit(b, 2, voice=False)
    with pytest.raises(JobRunning) as running_exc:
        jobs.submit(a, 2, voice=False)
    assert running_exc.value.job_id == first.job_id
    with pytest.raises(JobRunning) as queued_exc:
        jobs.submit(b, 2, voice=False)
    assert queued_exc.value.job_id == queued.job_id


def test_fifth_waiting_busy(rt: AgentRuntime, make_jobs: Callable[[FakeRun], ScorecardJobs]) -> None:
    run = FakeRun()
    jobs = make_jobs(run)
    first = jobs.submit(_agent(rt), 2, voice=False)
    assert run.started[0].wait(WAIT_S)
    waiting = [jobs.submit(_agent(rt), 2, voice=False) for _ in range(4)]
    assert [jobs.position(j.job_id) for j in waiting] == [1, 2, 3, 4]
    assert jobs.position(first.job_id) == 0
    with pytest.raises(JobBusy):
        jobs.submit(_agent(rt), 2, voice=False)


def test_failure_marks_failed_and_worker_survives(
        rt: AgentRuntime, make_jobs: Callable[[FakeRun], ScorecardJobs]) -> None:
    run = FakeRun(fail=True)
    jobs = make_jobs(run)
    bad = jobs.submit(_agent(rt), 2, voice=False)
    nxt = jobs.submit(_agent(rt), 2, voice=False)
    run.release.set()
    assert run.started[1].wait(WAIT_S)  # 두 번째가 시작했으면 첫 번째는 이미 끝났다
    failed = jobs.get(bad.job_id)
    assert failed.status == "failed"
    assert failed.report is None
    assert failed.error is not None
    assert failed.error["code"] == "internal"
    assert "secret" not in failed.error["message"]
    jobs.shutdown()
    assert jobs.get(nxt.job_id).status == "failed"


def test_get_unknown_key_error(make_jobs: Callable[[FakeRun], ScorecardJobs]) -> None:
    jobs = make_jobs(FakeRun())
    with pytest.raises(KeyError):
        jobs.get("sc_000000000000")
    assert jobs.position("sc_000000000000") == 0


def test_shutdown_stops_thread(rt: AgentRuntime,
                               make_jobs: Callable[[FakeRun], ScorecardJobs]) -> None:
    jobs = make_jobs(FakeRun())
    assert jobs._thread.is_alive()
    jobs.shutdown()
    assert not jobs._thread.is_alive()
    jobs.shutdown()  # 두 번 불러도 안전
    with pytest.raises(JobBusy):
        jobs.submit(_agent(rt), 2, voice=False)


def test_expired_agent_jobs(rt: AgentRuntime, clock: Clock,
                            make_jobs: Callable[[FakeRun], ScorecardJobs]) -> None:
    run = FakeRun()
    jobs = make_jobs(run, ttl_s=30 * 86400.0)  # 작업 보관 기간은 상담원 만료보다 길게
    preset = Agent("preset-test", "프리셋", "test", AgentSettings(), CHUNKS, clock.now, None)
    rt.store.add_preset(preset)
    a = _agent(rt)
    first = jobs.submit(a, 2, voice=False)
    assert run.started[0].wait(WAIT_S)
    doomed = jobs.submit(_agent(rt), 2, voice=False)
    kept = jobs.submit(preset, 2, voice=False)
    clock.now += 25 * 3600  # 사용자 상담원 만료 (store.get 이 바로 지워 sweep 결과엔 안 잡힌다)
    run.release.set()
    assert run.started[1].wait(WAIT_S)  # 만료된 상담원 작업을 건너뛰고 프리셋 작업이 시작됐다
    jobs.shutdown()
    assert [c[0] for c in run.calls] == [a.agent_id, preset.agent_id]
    with pytest.raises(KeyError):
        jobs.get(first.job_id)  # 만료된 상담원의 끝난 작업은 정리된다
    with pytest.raises(KeyError):
        jobs.get(doomed.job_id)
    assert jobs.get(kept.job_id).status == "done"


def test_finished_jobs_expire_after_ttl(rt: AgentRuntime, clock: Clock,
                                        make_jobs: Callable[[FakeRun], ScorecardJobs]) -> None:
    run = FakeRun()
    jobs = make_jobs(run)
    preset = Agent("preset-test", "프리셋", "test", AgentSettings(), CHUNKS, clock.now, None)
    rt.store.add_preset(preset)
    job = jobs.submit(preset, 2, voice=False)
    assert run.started[0].wait(WAIT_S)
    run.release.set()
    jobs.shutdown()
    assert jobs.get(job.job_id).status == "done"
    clock.now += 86400.0
    with pytest.raises(KeyError):
        jobs.get(job.job_id)
