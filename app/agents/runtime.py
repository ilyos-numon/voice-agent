"""상담원 실행에 필요한 것(저장소·세션·관문·STT/TTS·검색 색인·LLM 팩토리)을 묶는다."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.agents.limits import SessionBook, TurnGate
from app.agents.models import Agent
from app.agents.presets import Preset, load_presets
from app.agents.retrieval import ChunkIndex
from app.agents.store import AgentNotFound, AgentStore
from app.config import Settings
from app.pipeline.llm_qwen import QwenLLM
from app.pipeline.stubs import PassthroughSTT, SilentTTS
from app.pipeline.types import STT, TTS, SentenceStreamingLLM

LLMFactory = Callable[[str], SentenceStreamingLLM]
VOICE_STYLE: dict[str, str] = {
    "calm_female": "F1",
    "bright_female": "F2",
    "calm_male": "M1",
    "deep_male": "M2",
}
FALLBACK_STYLE = "F1"


@dataclass
class AgentRuntime:
    store: AgentStore
    sessions: SessionBook
    gate: TurnGate
    stt: STT
    tts: TTS
    presets: list[Preset]
    llm_factory: LLMFactory | None
    voice_capable: bool
    limits: Settings
    _indexes: dict[str, ChunkIndex] = field(default_factory=dict, init=False, repr=False)
    _voices: dict[str, TTS] = field(default_factory=dict, init=False, repr=False)
    _missing: set[str] = field(default_factory=set, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def _is_live(self, agent_id: str) -> bool:
        try:
            self.store.get(agent_id)
        except AgentNotFound:
            return False
        return True

    def index_for(self, agent: Agent) -> ChunkIndex:
        with self._lock:
            for aid in [a for a in self._indexes if a != agent.agent_id and not self._is_live(a)]:
                del self._indexes[aid]
            index = self._indexes.get(agent.agent_id)
            if index is None:
                index = ChunkIndex(agent.chunks)
                if self._is_live(agent.agent_id):
                    self._indexes[agent.agent_id] = index
            return index

    def _load_style(self, style: str) -> TTS | None:
        """for_voice 로 style 을 읽는다. 없는 이름이면 None (결과는 캐시)."""
        if style in self._voices:
            return self._voices[style]
        if style in self._missing:
            return None
        try:
            tts: TTS = self.tts.for_voice(style)  # type: ignore[attr-defined]
        except ValueError:
            self._missing.add(style)
            return None
        self._voices[style] = tts
        return tts

    def tts_for(self, voice: str) -> TTS:
        if not hasattr(self.tts, "for_voice"):
            return self.tts
        with self._lock:
            style = VOICE_STYLE.get(voice)
            tts = self._load_style(style) if style is not None else None
            if tts is None:
                tts = self._load_style(FALLBACK_STYLE)
            return tts if tts is not None else self.tts

    def voice_available(self, voice: str) -> bool:
        style = VOICE_STYLE.get(voice)
        if style is None:
            return False
        if not hasattr(self.tts, "for_voice"):
            return True  # 스텁 TTS는 목소리를 무시하므로 어떤 목소리든 받는다
        with self._lock:
            return self._load_style(style) is not None


def _qwen_factory(settings: Settings) -> LLMFactory:
    def make(prompt: str) -> SentenceStreamingLLM:
        return QwenLLM(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_s=settings.llm_timeout_s,
            early_chunk=settings.llm_early_chunk,
            system_prompt=prompt,
        )

    return make


def build_agent_runtime(
    settings: Settings,
    stt: STT,
    tts: TTS,
    *,
    llm_factory: LLMFactory | None = None,
    clock: Callable[[], float] = time.time,
) -> AgentRuntime:
    ttl_s = settings.agent_ttl_hours * 3600.0
    presets = load_presets(settings.presets_dir, clock=clock, summary_default=settings.agent_summary_default)
    store = AgentStore(ttl_s=ttl_s, max_agents=settings.max_agents, clock=clock)
    for preset in presets:
        store.add_preset(preset.agent)
    if llm_factory is None and settings.llm_backend == "qwen" and settings.llm_api_key:
        llm_factory = _qwen_factory(settings)
    return AgentRuntime(
        store=store,
        sessions=SessionBook(settings.session_max_questions, ttl_s=ttl_s, clock=clock),
        gate=TurnGate(settings.turn_concurrency, settings.turn_queue_max),
        stt=stt,
        tts=tts,
        presets=presets,
        llm_factory=llm_factory,
        voice_capable=not isinstance(stt, PassthroughSTT) and not isinstance(tts, SilentTTS),
        limits=settings,
    )
