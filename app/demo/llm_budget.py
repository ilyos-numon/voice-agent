"""데모 모드 LLM 요약 일일 호출 예산 (UTC 날짜 기준, 인메모리)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator

from app.agents.runtime import AgentRuntime, LLMFactory
from app.config import Settings
from app.demo.quota import utc_day
from app.pipeline.types import FaqItem, SentenceStreamingLLM

log = logging.getLogger(__name__)


class LLMBudget:
    def __init__(self, daily_calls: int, clock: Callable[[], float] = time.time) -> None:
        self._daily = daily_calls
        self._clock = clock
        self._lock = threading.Lock()
        self._day: tuple[int, int] = utc_day(clock())
        self._used = 0

    def _roll_locked(self) -> None:
        day = utc_day(self._clock())
        if day != self._day:
            self._day = day
            self._used = 0

    def try_take(self) -> bool:
        with self._lock:
            self._roll_locked()
            if self._used < self._daily:
                self._used += 1
                return True
            return False

    def used_today(self) -> int:
        with self._lock:
            self._roll_locked()
            return self._used


class _BudgetedLLM:
    def __init__(self, inner: SentenceStreamingLLM, budget: LLMBudget) -> None:
        self._inner = inner
        self._budget = budget

    def stream_sentences(self, query: str, context: list[FaqItem]) -> Iterator[str]:
        if not self._budget.try_take():
            return
        try:
            yield from self._inner.stream_sentences(query, context)
        except Exception as exc:  # noqa: BLE001 - 어떤 실패든 규칙 문장으로 돌아가게 한다
            log.warning("demo llm failed: %s", type(exc).__name__)

    def answer(self, query: str, context: list[FaqItem]) -> str:
        return " ".join(self.stream_sentences(query, context))


def budgeted_factory(factory: LLMFactory, budget: LLMBudget) -> LLMFactory:
    def make(prompt: str) -> SentenceStreamingLLM:
        return _BudgetedLLM(factory(prompt), budget)

    return make


def apply_llm_budget(runtime: AgentRuntime, settings: Settings) -> None:
    if not settings.demo_mode or runtime.llm_factory is None:
        return
    runtime.llm_factory = budgeted_factory(runtime.llm_factory, LLMBudget(settings.demo_llm_daily_calls))
