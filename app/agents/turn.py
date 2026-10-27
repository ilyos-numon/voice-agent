"""상담원 한 턴: 이벤트 meta → sentence×N → done. 질문·전사·문서 문장은 로그에 쓰지 않는다."""

from __future__ import annotations

import secrets
import time
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from app.agents.compose import (
    AVOIDED_TEXT,
    SENTENCE_LIMIT,
    is_unknown,
    matches_avoid,
    select_sentences,
    shape_sentences,
    system_prompt,
    unknown_sentence,
)
from app.agents.grounding import Evidence, GroundedSentence, ground_sentences
from app.agents.models import Agent, AgentSettings, AnswerKind
from app.agents.retrieval import Candidate
from app.agents.runtime import AgentRuntime
from app.pipeline.audio import NoSpeechError
from app.pipeline.sentences import split_sentences
from app.pipeline.types import TTS, FaqItem


@dataclass(frozen=True)
class TurnMeta:
    turn_id: str
    transcript: str
    answer_kind: AnswerKind
    sentence_count: int
    candidates: list[Candidate]
    timings: dict[str, float]  # listen_ms, search_ms, think_ms


@dataclass(frozen=True)
class TurnSentence:
    index: int
    text: str
    supported: bool
    evidence: tuple[Evidence, ...]
    audio_wav: bytes
    speak_ms: float
    elapsed_ms: float


@dataclass(frozen=True)
class TurnDone:
    turn_id: str
    sentence_count: int
    answer_kind: AnswerKind
    summary_used: bool
    timings: dict[str, float]  # listen_ms, search_ms, think_ms, speak_ms, first_audio_ms, total_ms


TurnEvent = TurnMeta | TurnSentence | TurnDone

_Spoken = Future[tuple[bytes, float]]


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


def _timed_tts(tts: TTS, sentence: str) -> tuple[bytes, float]:
    t = time.perf_counter()
    wav = tts.synthesize(sentence)
    return wav, _ms(t)


def _to_faq(c: Candidate) -> FaqItem:
    ch = c.chunk
    return FaqItem(id=ch.chunk_id, question=ch.title, answer=ch.text, source=ch.origin)


def _chunk_sentences(c: Candidate) -> list[str]:
    return split_sentences(c.chunk.text) or [c.chunk.text]


def _rule_sentences(s: AgentSettings, transcript: str, candidates: list[Candidate]) -> list[str]:
    picked = select_sentences(transcript, _chunk_sentences(candidates[0]), SENTENCE_LIMIT[s.answer_length])
    return shape_sentences(picked, s, transcript)


def _summarize(
    rt: AgentRuntime, s: AgentSettings, transcript: str, candidates: list[Candidate],
    tts: TTS, pool: ThreadPoolExecutor,
) -> tuple[list[str], _Spoken | None]:
    """LLM 요약. 첫 문장은 말투를 입혀 TTS에 먼저 보낸다 (ADR-007 패턴)."""
    assert rt.llm_factory is not None
    llm = rt.llm_factory(system_prompt(s))
    limit = SENTENCE_LIMIT[s.answer_length]
    raw: list[str] = []
    first: _Spoken | None = None
    for sentence in llm.stream_sentences(transcript, [_to_faq(c) for c in candidates]):
        if not sentence.strip():
            continue
        if first is None:
            first = pool.submit(_timed_tts, tts, shape_sentences([sentence], s, transcript)[0])
        raw.append(sentence)
        if len(raw) >= limit:
            break
    if not raw:
        return _rule_sentences(s, transcript, candidates), None
    return shape_sentences(raw, s, transcript), first


def _fixed(text: str) -> list[GroundedSentence]:
    return [GroundedSentence(index=0, text=text, supported=False, evidence=())]


def iter_turn(
    rt: AgentRuntime, agent: Agent, *, text: str | None = None, audio: bytes | None = None,
    settings: AgentSettings | None = None,
) -> Iterator[TurnEvent]:
    s = settings if settings is not None else agent.settings
    t0 = time.perf_counter()
    t = time.perf_counter()
    transcript = rt.stt.transcribe(audio, text)
    listen_ms = _ms(t)
    if not transcript.strip():
        raise NoSpeechError("no speech detected")
    turn_id = "t_" + secrets.token_hex(6)
    tts = rt.tts_for(s.voice)

    with ThreadPoolExecutor(max_workers=1) as pool:
        kind: AnswerKind
        candidates: list[Candidate] = []
        first: _Spoken | None = None
        summary_used = False
        search_ms = think_ms = 0.0
        if matches_avoid(transcript, s.avoid_topics):
            kind, grounded = "avoided", _fixed(AVOIDED_TEXT)
        else:
            t = time.perf_counter()
            candidates = rt.index_for(agent).search(transcript)
            search_ms = _ms(t)
            if is_unknown(transcript, candidates):
                kind, grounded = "unknown", _fixed(unknown_sentence(s))
            else:
                kind = "grounded"
                t = time.perf_counter()
                if s.summary and rt.llm_factory is not None:
                    sentences, first = _summarize(rt, s, transcript, candidates, tts, pool)
                    summary_used = first is not None  # LLM이 빈 출력이면 조각 원문으로 대체했다
                else:
                    sentences = _rule_sentences(s, transcript, candidates)
                think_ms = _ms(t)
                grounded = ground_sentences(sentences, candidates)

        base = {"listen_ms": listen_ms, "search_ms": search_ms, "think_ms": think_ms}
        yield TurnMeta(turn_id, transcript, kind, len(grounded), candidates, dict(base))

        speak_total = 0.0
        first_audio_ms = 0.0
        for g in grounded:
            if g.index == 0 and first is not None:
                wav, speak_ms = first.result()
            else:
                wav, speak_ms = _timed_tts(tts, g.text)
            speak_total += speak_ms
            elapsed = _ms(t0)
            if g.index == 0:
                first_audio_ms = elapsed
            yield TurnSentence(g.index, g.text, g.supported, g.evidence, wav, speak_ms, elapsed)

    timings = {**base, "speak_ms": round(speak_total, 3), "first_audio_ms": first_audio_ms,
               "total_ms": _ms(t0)}
    yield TurnDone(turn_id, len(grounded), kind, summary_used, timings)
