import math
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.agents.models import Agent, AgentSettings, Chunk
from app.agents.questions import ScoreQuestion, make_questions
from app.agents.retrieval import Candidate
from app.agents.runtime import AgentRuntime, build_agent_runtime
from app.agents.scorecard import CAVEAT, percentile, run_scorecard
from app.config import Settings
from app.pipeline.stubs import PassthroughSTT, SilentTTS
from app.pipeline.wav import pcm16_to_wav

PARKING = "건물 지하 1층에 주차장이 있습니다. 방문객은 2시간 무료입니다."
HOURS = "평일 오전 9시부터 오후 6시까지 운영합니다. 주말은 휴무입니다."
CHUNKS = (
    Chunk("q-001", "주차 가능한가요?", PARKING, "주차 가능한가요?", "faq_csv"),
    Chunk("q-002", "영업 시간은 언제인가요?", HOURS, "영업 시간은 언제인가요?", "faq_csv"),
)
REPORT_KEYS = {
    "agent_id", "question_count", "generated_by", "caveat", "text", "voice",
    "voice_unavailable_reason", "by_style", "first_audio_ms", "first_audio_basis",
    "failures", "hints",
}


@pytest.fixture(autouse=True)
def _forget_av() -> Iterator[None]:
    """음성 채널은 av로 디코드한다. 다른 테스트의 "stub는 av를 읽지 않는다" 검사를 흐리지 않게 되돌린다."""
    before = set(sys.modules)
    yield
    for name in [m for m in sys.modules if m not in before and (m == "av" or m.startswith("av."))]:
        del sys.modules[name]


def _tone_wav(text: str) -> bytes:
    t = np.arange(4800, dtype=np.float32) / 16000.0
    pcm = (0.3 * np.sin(2 * np.pi * 220.0 * t) * 32767).astype("<i2")
    return pcm16_to_wav(pcm.tobytes(), 16000, 1)


class FakeTTS:
    def __init__(self, style: str = "F1", log: list[str] | None = None) -> None:
        self.style = style
        self.log: list[str] = log if log is not None else []
        self.texts: list[str] = []

    def for_voice(self, voice: str) -> "FakeTTS":
        self.log.append(voice)
        return FakeTTS(voice, self.log)

    def synthesize(self, text: str) -> bytes:
        self.texts.append(text)
        return _tone_wav(text)


class FixedSTT:
    def __init__(self, transcript: str) -> None:
        self.transcript = transcript
        self.audio: list[bytes | None] = []

    def transcribe(self, audio: bytes | None, text_hint: str | None) -> str:
        self.audio.append(audio)
        return self.transcript if audio is not None else (text_hint or "")


def _rt(tmp_path: Path, stt: Any = None, tts: Any = None) -> AgentRuntime:
    settings = Settings(_env_file=None, presets_dir=tmp_path, llm_backend="stub")  # type: ignore[call-arg]
    return build_agent_runtime(settings, stt or PassthroughSTT(), tts or SilentTTS())


def _agent(rt: AgentRuntime, chunks: tuple[Chunk, ...] = CHUNKS) -> Agent:
    return rt.store.create("테스트", AgentSettings(), chunks)


def _qs(*items: tuple[str, str, str]) -> list[ScoreQuestion]:
    return [ScoreQuestion(f"sq-{i:02d}", t, s, c)  # type: ignore[arg-type]
            for i, (t, s, c) in enumerate(items, start=1)]


# --- percentile ---------------------------------------------------------------

def test_percentile_empty_and_single() -> None:
    assert percentile([], 50) == 0.0
    assert percentile([7.0], 50) == 7.0
    assert percentile([7.0], 95) == 7.0


def test_percentile_nearest_rank_bounds() -> None:
    vals = [float(v) for v in range(10, 0, -1)]  # 순서 무관
    assert percentile(vals, 50) == 5.0
    assert percentile(vals, 95) == 10.0
    assert percentile(vals, 0) == 1.0
    assert percentile(vals, 100) == 10.0
    assert percentile(vals, 10) == 1.0
    assert percentile(vals, 11) == 2.0
    assert percentile([1.0, 2.0], 50) == 1.0
    assert percentile([1.0, 2.0], 51) == 2.0


# --- stub 런타임 ----------------------------------------------------------------

def test_stub_runtime_text_only(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    assert rt.voice_capable is False
    agent = _agent(rt)
    qs = make_questions(agent, 4)
    seen: list[tuple[int, int]] = []
    report = run_scorecard(rt, agent, qs, voice=True, progress=lambda d, t: seen.append((d, t)))
    assert set(report) == REPORT_KEYS
    assert report["agent_id"] == agent.agent_id
    assert report["question_count"] == len(qs) == 4
    assert report["generated_by"] == "rules"
    assert report["caveat"] == CAVEAT
    assert report["voice"] is None
    assert report["voice_unavailable_reason"] == "stub_audio"
    assert report["first_audio_basis"] == "text"
    assert report["text"]["total"] == 4
    assert report["by_style"]["verbatim"]["total"] == 2
    assert report["by_style"]["colloquial"]["total"] == 2
    assert seen[-1] == (4, 4) and [d for d, _ in seen] == [1, 2, 3, 4]
    assert set(report["first_audio_ms"]) == {"p50", "p95"}
    assert rt.gate.running == 0 and rt.gate.waiting == 0


def test_voice_false_skips_voice_channel(tmp_path: Path) -> None:
    tts = FakeTTS()
    rt = _rt(tmp_path, stt=FixedSTT("주차 가능한가요?"), tts=tts)
    assert rt.voice_capable is True
    agent = _agent(rt)
    seen: list[tuple[int, int]] = []
    report = run_scorecard(rt, agent, make_questions(agent, 4), voice=False,
                           progress=lambda d, t: seen.append((d, t)))
    assert report["voice"] is None
    assert report["first_audio_basis"] == "text"
    assert seen[-1] == (4, 4)


def test_hit_counts_and_failure_reasons(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    agent = _agent(rt)
    qs = _qs(("주차 가능한가요?", "verbatim", "q-001"),
             ("주차 가능한가요?", "colloquial", "q-002"),   # 다른 조각이 1위 → wrong_chunk
             ("환불 규정 알려주세요", "colloquial", "q-002"))  # 모름 → no_answer
    report = run_scorecard(rt, agent, qs, voice=False)
    assert report["text"] == {"hits": 1, "total": 3}
    assert report["by_style"] == {"verbatim": {"hits": 1, "total": 1},
                                  "colloquial": {"hits": 0, "total": 2}}
    f1, f2 = report["failures"]
    assert f1["qid"] == "sq-02" and f1["reason"] == "wrong_chunk" and f1["channel"] == "text"
    assert f1["expected"] == {"chunk_id": "q-002", "title": "영업 시간은 언제인가요?"}
    assert f1["got"] == {"chunk_id": "q-001", "title": "주차 가능한가요?"}
    assert f1["heard"] is None and f1["style"] == "colloquial" and f1["question"] == "주차 가능한가요?"
    assert f2["qid"] == "sq-03" and f2["reason"] == "no_answer"


# --- 음성 채널 ------------------------------------------------------------------

def test_voice_channel_misheard(tmp_path: Path) -> None:
    tts = FakeTTS()
    stt = FixedSTT("영업 시간은 언제인가요?")  # 무엇을 물어도 영업 시간으로 알아듣는다
    rt = _rt(tmp_path, stt=stt, tts=tts)
    agent = _agent(rt)
    qs = _qs(("주차 가능한가요?", "verbatim", "q-001"),
             ("영업 시간은 언제인가요?", "verbatim", "q-002"))
    seen: list[tuple[int, int]] = []
    report = run_scorecard(rt, agent, qs, voice=True, progress=lambda d, t: seen.append((d, t)))
    assert report["text"] == {"hits": 2, "total": 2}
    assert report["voice"] == {"hits": 1, "total": 2}
    assert report["voice_unavailable_reason"] is None
    assert report["first_audio_basis"] == "voice"
    assert seen[-1] == (4, 4)
    (fail,) = report["failures"]
    assert fail["qid"] == "sq-01" and fail["channel"] == "voice" and fail["reason"] == "misheard"
    assert fail["heard"] == "영업 시간은 언제인가요?"
    assert fail["got"]["chunk_id"] == "q-002"
    codes = [h["code"] for h in report["hints"]]
    assert "misheard" in codes
    hint = next(h for h in report["hints"] if h["code"] == "misheard")
    assert hint["chunk_ids"] == ["q-001"]
    # 질문 음성은 calm_male(M1)로 만들고, 16 kHz WAV 앞뒤 400 ms 무음이 붙는다
    assert "M1" in tts.log
    voice_audio = [a for a in stt.audio if a is not None]
    assert len(voice_audio) == 2
    n_samples = (len(voice_audio[0]) - 44) // 2
    assert n_samples == 4800 + 2 * 6400


def test_voice_audio_is_deterministic(tmp_path: Path) -> None:
    def run() -> list[bytes]:
        stt = FixedSTT("주차 가능한가요?")
        rt = _rt(tmp_path, stt=stt, tts=FakeTTS())
        agent = _agent(rt)
        run_scorecard(rt, agent, make_questions(agent, 4), voice=True)
        return [a for a in stt.audio if a is not None]

    assert run() == run()


# --- 힌트 -----------------------------------------------------------------------

class ForcedIndex:
    def __init__(self, top: Chunk, second: Chunk) -> None:
        self.top, self.second = top, second

    def search(self, query: str, top_k: int = 3) -> list[Candidate]:
        return [Candidate(self.top, 5.0, 1), Candidate(self.second, 4.0, 2)][:top_k]


def test_similar_chunks_hint_names_both_titles(tmp_path: Path) -> None:
    a = Chunk("q-001", "주차 요금은 얼마인가요?", "주차 요금은 30분에 1000원입니다.",
              "주차 요금은 얼마인가요?", "faq_csv")
    b = Chunk("q-002", "주차 요금 할인이 되나요?", "주차 요금은 영수증이 있으면 할인됩니다.",
              "주차 요금 할인이 되나요?", "faq_csv")
    rt = _rt(tmp_path)
    agent = _agent(rt, (a, b))
    rt.index_for = lambda _agent: ForcedIndex(b, a)  # type: ignore[method-assign]
    qs = _qs(("주차 요금은 얼마인가요?", "verbatim", "q-001"),
             ("주차 요금 할인이 되나요?", "verbatim", "q-002"))
    report = run_scorecard(rt, agent, qs, voice=False)
    assert report["text"]["hits"] == 1
    hint = report["hints"][0]
    assert hint["code"] == "similar_chunks"
    assert a.title in hint["message"] and b.title in hint["message"]
    assert hint["chunk_ids"] == ["q-001", "q-002"]


def test_long_chunks_and_colloquial_gap_hints(tmp_path: Path) -> None:
    long_text = "주차장은 지하에 있습니다. " * 50
    a = Chunk("q-001", "주차 가능한가요?", long_text, "주차 가능한가요?", "faq_csv")
    b = Chunk("q-002", "영업 시간은 언제인가요?", HOURS, "영업 시간은 언제인가요?", "faq_csv")
    assert len(long_text) > 600
    rt = _rt(tmp_path)
    agent = _agent(rt, (a, b))
    qs = _qs(("주차 가능한가요?", "verbatim", "q-001"),
             ("영업 시간은 언제인가요?", "verbatim", "q-002"),
             ("영업 시간은 언제인가요?", "colloquial", "q-001"))  # 긴 조각을 기대, 다른 조각 적중
    report = run_scorecard(rt, agent, qs, voice=False)
    codes = [h["code"] for h in report["hints"]]
    assert codes == ["similar_chunks", "long_chunks", "colloquial_gap"]
    long_hint = report["hints"][1]
    assert long_hint["chunk_ids"] == ["q-001"]
    assert len(report["hints"]) <= 3


def test_no_hints_when_all_hit(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    agent = _agent(rt)
    qs = _qs(("주차 가능한가요?", "verbatim", "q-001"),
             ("영업 시간은 언제인가요?", "verbatim", "q-002"))
    report = run_scorecard(rt, agent, qs, voice=False)
    assert report["failures"] == [] and report["hints"] == []
    assert not math.isnan(report["first_audio_ms"]["p50"])
