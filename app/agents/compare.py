"""같은 질문을 두 설정(A → B 순차)으로 답해 차이를 보여 준다 (§4.3 CompareOut, questions_left 제외)."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

from app.agents.limits import Busy
from app.agents.models import Agent, AgentSettings, merge_settings, settings_to_dict
from app.agents.retrieval import Candidate
from app.agents.runtime import AgentRuntime
from app.agents.turn import TurnDone, TurnMeta, TurnSentence, iter_turn

WAIT_TIMEOUT_S = 60.0
FIRST_AUDIO_NOTE_MS = 200.0


def _candidate_out(c: Candidate) -> dict[str, Any]:
    return {"rank": c.rank, "chunk_id": c.chunk.chunk_id, "title": c.chunk.title,
            "score": round(c.score, 2)}


def _sentence_out(s: TurnSentence) -> dict[str, Any]:
    return {
        "index": s.index,
        "text": s.text,
        "supported": s.supported,
        "evidence": [{"chunk_id": e.chunk_id, "title": e.title, "quote": e.quote,
                      "overlap": e.overlap} for e in s.evidence],
        "audio_wav_b64": base64.b64encode(s.audio_wav).decode("ascii"),
        "speak_ms": round(s.speak_ms, 1),
    }


def _run_side(rt: AgentRuntime, agent: Agent, question: str, s: AgentSettings) -> dict[str, Any]:
    ticket = rt.gate.enter()
    try:
        if not ticket.wait(WAIT_TIMEOUT_S):
            raise Busy("대기 시간이 지났습니다")
        meta: TurnMeta | None = None
        done: TurnDone | None = None
        sentences: list[TurnSentence] = []
        for ev in iter_turn(rt, agent, text=question, settings=s):
            if isinstance(ev, TurnMeta):
                meta = ev
            elif isinstance(ev, TurnSentence):
                sentences.append(ev)
            else:
                done = ev
    finally:
        ticket.release()
    assert meta is not None and done is not None
    answer = " ".join(x.text for x in sentences)
    return {
        "settings": settings_to_dict(s),
        "answer_kind": done.answer_kind,
        "answer": answer,
        "sentence_count": done.sentence_count,
        "char_count": len(answer),
        "summary_used": done.summary_used,
        "candidates": [_candidate_out(c) for c in meta.candidates],
        "sentences": [_sentence_out(x) for x in sentences],
        "timings": {k: round(v, 1) for k, v in done.timings.items()},
    }


def _supported_count(side: Mapping[str, Any]) -> int:
    return sum(1 for x in side["sentences"] if x["supported"])


def _notes(diff: Mapping[str, Any], supported_a: int, supported_b: int) -> list[str]:
    notes: list[str] = []
    d_audio = float(diff["first_audio_ms"])
    if abs(d_audio) >= FIRST_AUDIO_NOTE_MS:
        way = "늦게" if d_audio > 0 else "빨리"
        notes.append(f"B가 첫 음성을 {abs(d_audio) / 1000:.1f}초 {way} 시작합니다.")
    d_sent = int(diff["sentence_count"])
    if d_sent != 0:
        way = "깁니다" if d_sent > 0 else "짧습니다"
        notes.append(f"B의 답이 {abs(d_sent)}문장 {way}.")
    if supported_a != supported_b:
        notes.append(f"근거 있는 문장: A {supported_a}개 · B {supported_b}개")
    if not notes:
        notes.append("두 설정의 차이가 작습니다.")
    return notes


def compare_settings(rt: AgentRuntime, agent: Agent, question: str,
                     a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    settings_a = merge_settings(agent.settings, a)
    settings_b = merge_settings(agent.settings, b)
    side_a = _run_side(rt, agent, question, settings_a)
    side_b = _run_side(rt, agent, question, settings_b)
    diff = {
        "first_audio_ms": round(side_b["timings"]["first_audio_ms"]
                                - side_a["timings"]["first_audio_ms"], 1),
        "sentence_count": side_b["sentence_count"] - side_a["sentence_count"],
        "char_count": side_b["char_count"] - side_a["char_count"],
    }
    return {
        "question": question,
        "a": side_a,
        "b": side_b,
        "diff": diff,
        "notes": _notes(diff, _supported_count(side_a), _supported_count(side_b)),
    }
