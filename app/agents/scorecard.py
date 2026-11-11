"""성적표: 규칙 질문을 글자·음성 채널로 상담원에게 묻고 적중·실패·힌트를 낸다 (§4.3 ReportOut)."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.agents.models import Agent, AnswerKind, Chunk
from app.agents.questions import ScoreQuestion
from app.agents.runtime import AgentRuntime
from app.agents.turn import TurnDone, TurnMeta, iter_turn
from app.pipeline.audio import AudioDecodeError, NoSpeechError

CAVEAT = "질문은 규칙으로 만든 것이라 실제 사람 말투보다 쉬워 점수가 높게 나올 수 있습니다."
VOICE_ID = "calm_male"
SAMPLE_RATE = 16000
PAD_MS = 400
DITHER_STD = 1e-4
LONG_CHUNK_CHARS = 600
COLLOQUIAL_GAP_POINTS = 20.0
MAX_HINTS = 3
WAIT_STEP_S = 1.0


def percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = math.ceil(p / 100.0 * len(ordered))
    rank = min(max(rank, 1), len(ordered))
    return float(ordered[rank - 1])


@dataclass(frozen=True)
class _Outcome:
    top: Chunk | None
    kind: AnswerKind | None   # None = 음성 없음·디코드 실패로 턴이 끝나지 않음
    first_audio_ms: float | None
    heard: str

    def hit(self, expected: str) -> bool:
        return self.kind == "grounded" and self.top is not None and self.top.chunk_id == expected


def _ask(rt: AgentRuntime, agent: Agent, *, text: str | None = None,
         audio: bytes | None = None) -> _Outcome:
    top: Chunk | None = None
    kind: AnswerKind | None = None
    heard = ""
    first: float | None = None
    try:
        for ev in iter_turn(rt, agent, text=text, audio=audio):
            if isinstance(ev, TurnMeta):
                top = ev.candidates[0].chunk if ev.candidates else None
                kind = ev.answer_kind
                heard = ev.transcript
            elif isinstance(ev, TurnDone):
                first = ev.timings["first_audio_ms"]
    except (NoSpeechError, AudioDecodeError):
        return _Outcome(None, None, None, "")
    return _Outcome(top, kind, first, heard)


def _question_audio(rt: AgentRuntime, text: str, ordinal: int) -> bytes:
    """calm_male 목소리로 질문을 합성해 16 kHz, 앞뒤 400 ms 무음을 붙인다 (bench/make_audio.py 방식)."""
    import numpy as np

    from app.pipeline.audio import decode_audio
    from app.pipeline.wav import pcm16_to_wav

    speech = decode_audio(rt.tts_for(VOICE_ID).synthesize(text), sample_rate=SAMPLE_RATE)
    pad = np.zeros(SAMPLE_RATE * PAD_MS // 1000, dtype=np.float32)
    signal = np.concatenate([pad, speech, pad])
    rng = np.random.default_rng(ordinal)
    signal = signal + rng.normal(0.0, DITHER_STD, size=signal.shape).astype(np.float32)
    pcm = (np.clip(signal, -1.0, 32767 / 32768) * 32768.0).round().astype("<i2")
    return pcm16_to_wav(pcm.tobytes(), SAMPLE_RATE, 1)


def _ref(chunk: Chunk | None) -> dict[str, str] | None:
    return None if chunk is None else {"chunk_id": chunk.chunk_id, "title": chunk.title}


def _failure(q: ScoreQuestion, channel: str, expected: Chunk | None, out: _Outcome,
             reason: str) -> dict[str, Any]:
    exp = _ref(expected) or {"chunk_id": q.expected_chunk_id, "title": ""}
    return {
        "qid": q.qid, "question": q.text, "style": q.style, "channel": channel,
        "expected": exp, "got": _ref(out.top),
        "heard": out.heard if channel == "voice" else None, "reason": reason,
    }


def _rate(hits: int, total: int) -> float:
    return 100.0 * hits / total if total else 0.0


def _hints(failures: list[dict[str, Any]], by_style: dict[str, dict[str, int]],
           chunks: dict[str, Chunk]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []

    pairs = Counter(
        tuple(sorted((f["expected"]["chunk_id"], f["got"]["chunk_id"])))
        for f in failures
        if f["channel"] == "text" and f["reason"] == "wrong_chunk" and f["got"] is not None
    )
    if pairs:
        pair = min(pairs, key=lambda k: (-pairs[k], k))
        t1, t2 = (chunks[c].title if c in chunks else c for c in pair)
        hints.append({
            "code": "similar_chunks",
            "message": f"'{t1}'와(과) '{t2}' 내용이 비슷해 서로 헷갈립니다. "
                       "제목이나 첫 문장을 더 구별되게 바꿔 보세요.",
            "chunk_ids": list(pair),
        })

    misheard = sorted({f["expected"]["chunk_id"] for f in failures if f["reason"] == "misheard"})
    if misheard:
        n = sum(1 for f in failures if f["reason"] == "misheard")
        hints.append({
            "code": "misheard",
            "message": f"글자로는 맞혔지만 음성으로 물었을 때 {n}개 질문을 잘못 알아들었습니다. "
                       "발음이 비슷한 낱말이나 줄임말을 풀어 써 보세요.",
            "chunk_ids": misheard,
        })

    involved: set[str] = set()
    for f in failures:
        involved.add(f["expected"]["chunk_id"])
        if f["got"] is not None:
            involved.add(f["got"]["chunk_id"])
    long_ids = sorted(c for c in involved if c in chunks and len(chunks[c].text) > LONG_CHUNK_CHARS)
    if long_ids:
        hints.append({
            "code": "long_chunks",
            "message": f"틀린 질문과 관련된 조각 {len(long_ids)}개가 {LONG_CHUNK_CHARS}자를 넘습니다. "
                       "긴 조각을 주제별로 나눠 보세요.",
            "chunk_ids": long_ids,
        })

    v, c = by_style["verbatim"], by_style["colloquial"]
    if v["total"] and c["total"]:
        gap = _rate(v["hits"], v["total"]) - _rate(c["hits"], c["total"])
        if gap >= COLLOQUIAL_GAP_POINTS:
            ids = sorted({f["expected"]["chunk_id"] for f in failures
                          if f["channel"] == "text" and f["style"] == "colloquial"})
            hints.append({
                "code": "colloquial_gap",
                "message": f"문서 그대로 물을 때보다 말투를 바꿔 물을 때 {gap:.0f}점 낮습니다. "
                           "자주 쓰는 다른 표현을 질문에 함께 적어 보세요.",
                "chunk_ids": ids,
            })
    return hints[:MAX_HINTS]


def run_scorecard(rt: AgentRuntime, agent: Agent, questions: Sequence[ScoreQuestion], *,
                  voice: bool = True,
                  progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    use_voice = voice and rt.voice_capable
    total_steps = len(questions) * (2 if use_voice else 1)
    chunks = {c.chunk_id: c for c in agent.chunks}
    done = 0
    text_hits = voice_hits = 0
    by_style: dict[str, dict[str, int]] = {
        "verbatim": {"hits": 0, "total": 0}, "colloquial": {"hits": 0, "total": 0},
    }
    text_first: list[float] = []
    voice_first: list[float] = []
    failures: list[dict[str, Any]] = []

    def step() -> None:
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, total_steps)

    for ordinal, q in enumerate(questions, start=1):
        expected = chunks.get(q.expected_chunk_id)
        ticket = rt.gate.enter(allow_overflow=True)
        try:
            while not ticket.wait(WAIT_STEP_S):
                pass
            out = _ask(rt, agent, text=q.text)
            text_ok = out.hit(q.expected_chunk_id)
            by_style[q.style]["total"] += 1
            if out.first_audio_ms is not None:
                text_first.append(out.first_audio_ms)
            if text_ok:
                text_hits += 1
                by_style[q.style]["hits"] += 1
            else:
                reason = "no_answer" if out.kind != "grounded" else "wrong_chunk"
                failures.append(_failure(q, "text", expected, out, reason))
            step()

            if use_voice:
                vout = _ask(rt, agent, audio=_question_audio(rt, q.text, ordinal))
                if vout.first_audio_ms is not None:
                    voice_first.append(vout.first_audio_ms)
                if vout.hit(q.expected_chunk_id):
                    voice_hits += 1
                else:
                    if text_ok:
                        reason = "misheard"
                    elif vout.kind != "grounded":
                        reason = "no_answer"
                    else:
                        reason = "wrong_chunk"
                    failures.append(_failure(q, "voice", expected, vout, reason))
                step()
        finally:
            ticket.release()

    basis = voice_first if use_voice else text_first
    n = len(questions)
    return {
        "agent_id": agent.agent_id,
        "question_count": n,
        "generated_by": "rules",
        "caveat": CAVEAT,
        "text": {"hits": text_hits, "total": n},
        "voice": {"hits": voice_hits, "total": n} if use_voice else None,
        "voice_unavailable_reason": "stub_audio" if voice and not rt.voice_capable else None,
        "by_style": by_style,
        "first_audio_ms": {"p50": round(percentile(basis, 50), 1),
                           "p95": round(percentile(basis, 95), 1)},
        "first_audio_basis": "voice" if use_voice else "text",
        "failures": failures,
        "hints": _hints(failures, by_style, chunks),
    }
