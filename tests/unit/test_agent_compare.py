import base64
from pathlib import Path

import pytest

from app.agents import compare
from app.agents.compare import _notes, compare_settings
from app.agents.limits import Busy, TurnGate
from app.agents.models import Agent, AgentSettings, Chunk
from app.agents.runtime import AgentRuntime, build_agent_runtime
from app.config import Settings
from app.pipeline.stubs import PassthroughSTT, SilentTTS

PARKING = "건물 지하 1층에 주차장이 있습니다. 방문객은 2시간 무료입니다. 이후 30분마다 1000원입니다."
HOURS = "평일 오전 9시부터 오후 6시까지 운영합니다. 주말은 휴무입니다."
CHUNKS = (
    Chunk("q-001", "주차 가능한가요?", PARKING, "주차 가능한가요?", "faq_csv"),
    Chunk("q-002", "영업 시간은 언제인가요?", HOURS, "영업 시간은 언제인가요?", "faq_csv"),
)
Q_PARK = "주차 돼요?"
SIDE_KEYS = {"settings", "answer_kind", "answer", "sentence_count", "char_count", "summary_used",
             "candidates", "sentences", "timings"}


def _rt(tmp_path: Path) -> AgentRuntime:
    settings = Settings(_env_file=None, presets_dir=tmp_path, llm_backend="stub")  # type: ignore[call-arg]
    return build_agent_runtime(settings, PassthroughSTT(), SilentTTS())


def _agent(rt: AgentRuntime) -> Agent:
    return rt.store.create("테스트", AgentSettings(), CHUNKS)


def test_one_sentence_vs_detailed(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    agent = _agent(rt)
    out = compare_settings(rt, agent, Q_PARK, {"answer_length": "one_sentence"},
                           {"answer_length": "detailed"})
    assert set(out) == {"question", "a", "b", "diff", "notes"}
    assert out["question"] == Q_PARK
    a, b = out["a"], out["b"]
    assert set(a) == SIDE_KEYS and set(b) == SIDE_KEYS
    assert a["settings"]["answer_length"] == "one_sentence"
    assert b["settings"]["answer_length"] == "detailed"
    assert a["answer_kind"] == b["answer_kind"] == "grounded"
    assert a["sentence_count"] == 1
    assert b["sentence_count"] >= 2
    assert a["char_count"] == len(a["answer"])
    assert a["candidates"][0]["chunk_id"] == "q-001"
    assert a["candidates"][0]["rank"] == 1
    s0 = a["sentences"][0]
    assert set(s0) == {"index", "text", "supported", "evidence", "audio_wav_b64", "speak_ms"}
    assert base64.b64decode(s0["audio_wav_b64"])
    assert set(a["timings"]) == {"listen_ms", "search_ms", "think_ms", "speak_ms",
                                 "first_audio_ms", "total_ms"}
    # diff = b − a
    d = out["diff"]
    assert d["sentence_count"] == b["sentence_count"] - a["sentence_count"]
    assert d["char_count"] == b["char_count"] - a["char_count"]
    assert d["first_audio_ms"] == round(b["timings"]["first_audio_ms"]
                                        - a["timings"]["first_audio_ms"], 1)
    assert f"B의 답이 {d['sentence_count']}문장 깁니다." in out["notes"]
    assert rt.gate.running == 0 and rt.gate.waiting == 0


def test_same_settings_small_difference(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    out = compare_settings(rt, _agent(rt), Q_PARK, {}, {})
    assert out["diff"]["sentence_count"] == 0
    assert out["notes"] == ["두 설정의 차이가 작습니다."]


def test_unknown_key_value_error(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    with pytest.raises(ValueError):
        compare_settings(rt, _agent(rt), Q_PARK, {"nope": 1}, {})


def test_notes_first_audio_later_and_earlier() -> None:
    assert _notes({"first_audio_ms": 1200.0, "sentence_count": 0}, 1, 1) == [
        "B가 첫 음성을 1.2초 늦게 시작합니다."]
    assert _notes({"first_audio_ms": -200.0, "sentence_count": 0}, 1, 1) == [
        "B가 첫 음성을 0.2초 빨리 시작합니다."]
    assert _notes({"first_audio_ms": 199.9, "sentence_count": 0}, 1, 1) == [
        "두 설정의 차이가 작습니다."]


def test_notes_sentence_count() -> None:
    assert _notes({"first_audio_ms": 0.0, "sentence_count": -2}, 1, 1) == [
        "B의 답이 2문장 짧습니다."]
    assert _notes({"first_audio_ms": 0.0, "sentence_count": 3}, 1, 1) == [
        "B의 답이 3문장 깁니다."]


def test_notes_supported_count() -> None:
    assert _notes({"first_audio_ms": 0.0, "sentence_count": 0}, 2, 1) == [
        "근거 있는 문장: A 2개 · B 1개"]


def test_notes_all_rules_in_order() -> None:
    assert _notes({"first_audio_ms": 1200.0, "sentence_count": -2}, 3, 1) == [
        "B가 첫 음성을 1.2초 늦게 시작합니다.",
        "B의 답이 2문장 짧습니다.",
        "근거 있는 문장: A 3개 · B 1개",
    ]


def test_notes_nothing() -> None:
    assert _notes({"first_audio_ms": 0.0, "sentence_count": 0}, 1, 1) == [
        "두 설정의 차이가 작습니다."]


def test_busy_when_queue_full(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    agent = _agent(rt)
    rt.gate = TurnGate(1, 0)
    holder = rt.gate.enter(allow_overflow=True)
    try:
        with pytest.raises(Busy):
            compare_settings(rt, agent, Q_PARK, {}, {})
    finally:
        holder.release()


def test_busy_when_wait_times_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rt = _rt(tmp_path)
    agent = _agent(rt)
    rt.gate = TurnGate(1, 1)
    monkeypatch.setattr(compare, "WAIT_TIMEOUT_S", 0.05)
    holder = rt.gate.enter()
    try:
        with pytest.raises(Busy):
            compare_settings(rt, agent, Q_PARK, {}, {})
        assert rt.gate.waiting == 0  # 시간이 지난 표는 대기열에서 빠진다
    finally:
        holder.release()
    assert rt.gate.running == 0
