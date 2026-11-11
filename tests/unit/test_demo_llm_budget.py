import calendar
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.agents.models import AgentSettings, Chunk
from app.agents.runtime import AgentRuntime, build_agent_runtime
from app.agents.turn import TurnDone, iter_turn
from app.config import Settings
from app.demo.llm_budget import LLMBudget, apply_llm_budget, budgeted_factory
from app.pipeline.stubs import PassthroughSTT, SilentTTS
from app.pipeline.types import FaqItem, SentenceStreamingLLM

T0 = float(calendar.timegm((2026, 10, 28, 12, 0, 0)))
NEXT_DAY = float(calendar.timegm((2026, 10, 29, 0, 0, 1)))
CTX = [FaqItem(id="q-001", question="주차 가능한가요?", answer="지하 1층에 있습니다.", source="합성")]
PARKING = "건물 지하 1층에 주차장이 있습니다. 방문객은 2시간 무료입니다."
CHUNKS = (Chunk("q-001", "주차 가능한가요?", PARKING, "주차 가능한가요?", "faq_csv"),)


class FakeClock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class CountingLLM:
    def __init__(self, sentences: list[str], fail_after: int | None = None) -> None:
        self.sentences = sentences
        self.fail_after = fail_after
        self.calls = 0

    def answer(self, query: str, context: list[FaqItem]) -> str:
        return " ".join(self.stream_sentences(query, context))

    def stream_sentences(self, query: str, context: list[FaqItem]) -> Iterator[str]:
        self.calls += 1
        for i, s in enumerate(self.sentences):
            if self.fail_after is not None and i >= self.fail_after:
                raise RuntimeError("secret-key-and-body")
            yield s
        if self.fail_after is not None and self.fail_after >= len(self.sentences):
            raise RuntimeError("secret-key-and-body")


def _factory(llm: SentenceStreamingLLM) -> Any:
    prompts: list[str] = []

    def make(prompt: str) -> SentenceStreamingLLM:
        prompts.append(prompt)
        return llm

    make.prompts = prompts  # type: ignore[attr-defined]
    return make


# ---- LLMBudget ----

def test_budget_take_and_used() -> None:
    b = LLMBudget(2, clock=FakeClock(T0))
    assert b.used_today() == 0
    assert b.try_take() is True
    assert b.try_take() is True
    assert b.try_take() is False
    assert b.used_today() == 2


def test_budget_zero_never_allows() -> None:
    b = LLMBudget(0, clock=FakeClock(T0))
    assert b.try_take() is False and b.used_today() == 0


def test_budget_resets_on_new_utc_day() -> None:
    clock = FakeClock(T0)
    b = LLMBudget(1, clock=clock)
    assert b.try_take() is True
    assert b.try_take() is False
    clock.t = NEXT_DAY
    assert b.used_today() == 0
    assert b.try_take() is True


# ---- budgeted_factory ----

def test_second_stream_does_not_call_inner_llm() -> None:
    inner = CountingLLM(["첫 문장입니다.", "둘째 문장입니다."])
    llm = budgeted_factory(_factory(inner), LLMBudget(1, clock=FakeClock(T0)))("P")
    assert list(llm.stream_sentences("q", CTX)) == ["첫 문장입니다.", "둘째 문장입니다."]
    assert inner.calls == 1
    assert list(llm.stream_sentences("q", CTX)) == []
    assert inner.calls == 1


def test_budget_shared_across_factory_calls_and_prompt_passed() -> None:
    inner = CountingLLM(["a"])
    base = _factory(inner)
    wrapped = budgeted_factory(base, LLMBudget(1, clock=FakeClock(T0)))
    assert list(wrapped("P1").stream_sentences("q", CTX)) == ["a"]
    assert list(wrapped("P2").stream_sentences("q", CTX)) == []
    assert base.prompts == ["P1", "P2"] and inner.calls == 1


def test_budget_taken_lazily_on_first_next() -> None:
    budget = LLMBudget(1, clock=FakeClock(T0))
    llm = budgeted_factory(_factory(CountingLLM(["a"])), budget)("P")
    gen = llm.stream_sentences("q", CTX)
    assert budget.used_today() == 0
    next(gen)
    assert budget.used_today() == 1


def test_inner_exception_yields_nothing_and_logs_type_only(caplog: pytest.LogCaptureFixture) -> None:
    inner = CountingLLM(["x"], fail_after=0)
    llm = budgeted_factory(_factory(inner), LLMBudget(5, clock=FakeClock(T0)))("P")
    with caplog.at_level(logging.WARNING, logger="app.demo.llm_budget"):
        assert list(llm.stream_sentences("q", CTX)) == []
    assert "demo llm failed: RuntimeError" in caplog.text
    assert "secret-key-and-body" not in caplog.text


def test_inner_exception_keeps_emitted_sentences() -> None:
    inner = CountingLLM(["하나.", "둘."], fail_after=1)
    llm = budgeted_factory(_factory(inner), LLMBudget(5, clock=FakeClock(T0)))("P")
    assert list(llm.stream_sentences("q", CTX)) == ["하나."]


def test_answer_joins_sentences() -> None:
    llm = budgeted_factory(_factory(CountingLLM(["하나.", "둘."])), LLMBudget(5, clock=FakeClock(T0)))("P")
    assert llm.answer("q", CTX) == "하나. 둘."


def test_new_day_allows_again() -> None:
    clock = FakeClock(T0)
    inner = CountingLLM(["a"])
    llm = budgeted_factory(_factory(inner), LLMBudget(1, clock=clock))("P")
    assert list(llm.stream_sentences("q", CTX)) == ["a"]
    assert list(llm.stream_sentences("q", CTX)) == []
    clock.t = NEXT_DAY
    assert list(llm.stream_sentences("q", CTX)) == ["a"]
    assert inner.calls == 2


# ---- apply_llm_budget ----

def _settings(tmp_path: Path, **kw: Any) -> Settings:
    return Settings(_env_file=None, presets_dir=tmp_path, llm_backend="stub", **kw)  # type: ignore[call-arg]


def _rt(tmp_path: Path, factory: Any = None, **kw: Any) -> AgentRuntime:
    return build_agent_runtime(_settings(tmp_path, **kw), PassthroughSTT(), SilentTTS(), llm_factory=factory)


def test_apply_noop_when_demo_off(tmp_path: Path) -> None:
    factory = _factory(CountingLLM(["a"]))
    rt = _rt(tmp_path, factory)
    apply_llm_budget(rt, _settings(tmp_path, demo_mode=False))
    assert rt.llm_factory is factory


def test_apply_noop_when_factory_none(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    apply_llm_budget(rt, _settings(tmp_path, demo_mode=True))
    assert rt.llm_factory is None


def test_apply_wraps_in_demo_mode(tmp_path: Path) -> None:
    inner = CountingLLM(["a"])
    factory = _factory(inner)
    rt = _rt(tmp_path, factory)
    apply_llm_budget(rt, _settings(tmp_path, demo_mode=True, demo_llm_daily_calls=1))
    assert rt.llm_factory is not None and rt.llm_factory is not factory
    llm = rt.llm_factory("P")
    assert list(llm.stream_sentences("q", CTX)) == ["a"]
    assert list(llm.stream_sentences("q", CTX)) == []
    assert inner.calls == 1


def _done(rt: AgentRuntime) -> TurnDone:
    agent = rt.store.create("테스트", AgentSettings(summary=True), CHUNKS)
    done = list(iter_turn(rt, agent, text="주차 돼요?"))[-1]
    assert isinstance(done, TurnDone)
    return done


def test_turn_with_zero_budget_uses_rule_sentences(tmp_path: Path) -> None:
    inner = CountingLLM(["요약 문장입니다."])
    rt = _rt(tmp_path, _factory(inner))
    apply_llm_budget(rt, _settings(tmp_path, demo_mode=True, demo_llm_daily_calls=0))
    done = _done(rt)
    assert done.summary_used is False
    assert done.sentence_count > 0
    assert inner.calls == 0


def test_turns_with_budget_one(tmp_path: Path) -> None:
    inner = CountingLLM(["요약 문장입니다."])
    rt = _rt(tmp_path, _factory(inner))
    apply_llm_budget(rt, _settings(tmp_path, demo_mode=True, demo_llm_daily_calls=1))
    assert _done(rt).summary_used is True
    assert _done(rt).summary_used is False
    assert inner.calls == 1


def test_turn_with_failing_llm_completes(tmp_path: Path) -> None:
    inner = CountingLLM(["x"], fail_after=0)
    rt = _rt(tmp_path, _factory(inner))
    apply_llm_budget(rt, _settings(tmp_path, demo_mode=True))
    done = _done(rt)
    assert done.summary_used is False and done.sentence_count > 0
