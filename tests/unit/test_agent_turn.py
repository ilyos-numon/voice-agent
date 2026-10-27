import dataclasses
import io
import json
import logging
import threading
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

import pytest

from app.agents.compose import AVOIDED_TEXT, FRIENDLY_PREFIX, UNKNOWN_TEXT
from app.agents.models import Agent, AgentSettings, Chunk
from app.agents.runtime import VOICE_STYLE, AgentRuntime, build_agent_runtime
from app.agents.turn import TurnDone, TurnEvent, TurnMeta, TurnSentence, iter_turn
from app.config import Settings
from app.pipeline.audio import AudioDecodeError, NoSpeechError
from app.pipeline.llm_qwen import SYSTEM_PROMPT, QwenLLM
from app.pipeline.stubs import PassthroughSTT, SilentTTS
from app.pipeline.tts_supertonic import SupertonicTTS
from app.pipeline.types import FaqItem, SentenceStreamingLLM

ROOT = Path(__file__).resolve().parents[2]
PARKING = "건물 지하 1층에 주차장이 있습니다. 방문객은 2시간 무료입니다. 이후 30분마다 1000원입니다."
HOURS = "평일 오전 9시부터 오후 6시까지 운영합니다. 주말은 휴무입니다."
CHUNKS = (
    Chunk("q-001", "주차 가능한가요?", PARKING, "주차 가능한가요?", "faq_csv"),
    Chunk("q-002", "영업 시간은 언제인가요?", HOURS, "영업 시간은 언제인가요?", "faq_csv"),
)
Q_PARK = "주차 돼요?"
Q_NONE = "환불 규정 알려주세요"


class SpyTTS:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.called = threading.Event()

    def synthesize(self, text: str) -> bytes:
        self.texts.append(text)
        self.called.set()
        return b"WAV:" + text.encode("utf-8")


class FakeLLM:
    def __init__(self, sentences: list[str], tts: SpyTTS | None = None) -> None:
        self.sentences = sentences
        self.tts = tts
        self.calls: list[tuple[str, list[FaqItem]]] = []
        self.tts_before_second: bool | None = None

    def answer(self, query: str, context: list[FaqItem]) -> str:
        return " ".join(self.stream_sentences(query, context))

    def stream_sentences(self, query: str, context: list[FaqItem]) -> Iterator[str]:
        self.calls.append((query, context))
        for i, s in enumerate(self.sentences):
            if i == 1 and self.tts is not None:
                self.tts_before_second = self.tts.called.wait(2.0)
            yield s


class Factory:
    def __init__(self, llm: SentenceStreamingLLM) -> None:
        self.llm = llm
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> SentenceStreamingLLM:
        self.prompts.append(prompt)
        return self.llm


class FixedSTT:
    def __init__(self, transcript: str) -> None:
        self.transcript = transcript
        self.audio: list[bytes | None] = []

    def transcribe(self, audio: bytes | None, text_hint: str | None) -> str:
        self.audio.append(audio)
        return self.transcript


def _settings(tmp_path: Path, **kw: Any) -> Settings:
    return Settings(_env_file=None, presets_dir=tmp_path, llm_backend="stub", **kw)  # type: ignore[call-arg]


def _rt(tmp_path: Path, stt: Any = None, tts: Any = None, factory: Any = None) -> AgentRuntime:
    return build_agent_runtime(_settings(tmp_path), stt or PassthroughSTT(), tts or SpyTTS(),
                               llm_factory=factory)


def _agent(rt: AgentRuntime, **kw: Any) -> Agent:
    return rt.store.create("테스트", AgentSettings(**kw), CHUNKS)


def _split(events: list[TurnEvent]) -> tuple[TurnMeta, list[TurnSentence], TurnDone]:
    meta, *sents, done = events
    assert isinstance(meta, TurnMeta) and isinstance(done, TurnDone)
    assert all(isinstance(s, TurnSentence) for s in sents)
    return meta, sents, done  # type: ignore[return-value]


def test_event_order_and_counts(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    agent = _agent(rt, answer_length="detailed")
    meta, sents, done = _split(list(iter_turn(rt, agent, text=Q_PARK)))
    assert meta.answer_kind == done.answer_kind == "grounded"
    assert meta.sentence_count == done.sentence_count == len(sents) == 3
    assert [s.index for s in sents] == [0, 1, 2]
    assert meta.turn_id == done.turn_id and meta.turn_id.startswith("t_") and len(meta.turn_id) == 14
    assert meta.transcript == Q_PARK
    assert meta.candidates[0].chunk.chunk_id == "q-001"
    assert sents[0].text == FRIENDLY_PREFIX + "건물 지하 1층에 주차장이 있습니다."
    assert all(s.supported for s in sents)
    assert sents[0].evidence[0].chunk_id == "q-001"
    assert sents[0].audio_wav == b"WAV:" + sents[0].text.encode("utf-8")
    assert done.summary_used is False


def test_timings_keys(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    meta, sents, done = _split(list(iter_turn(rt, _agent(rt), text=Q_PARK)))
    assert set(meta.timings) == {"listen_ms", "search_ms", "think_ms"}
    assert set(done.timings) == {"listen_ms", "search_ms", "think_ms", "speak_ms",
                                 "first_audio_ms", "total_ms"}
    assert done.timings["first_audio_ms"] == sents[0].elapsed_ms
    assert done.timings["speak_ms"] == pytest.approx(sum(s.speak_ms for s in sents), abs=0.01)


def test_answer_length_and_concise(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    _, sents, _ = _split(list(iter_turn(rt, _agent(rt, answer_length="one_sentence",
                                                   tone="concise"), text=Q_PARK)))
    assert [s.text for s in sents] == ["건물 지하 1층에 주차장이 있습니다."]


def test_settings_override(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    agent = _agent(rt)
    s = dataclasses.replace(agent.settings, answer_length="one_sentence")
    _, sents, _ = _split(list(iter_turn(rt, agent, text=Q_PARK, settings=s)))
    assert len(sents) == 1


def test_avoided_has_no_candidates_and_no_llm(tmp_path: Path) -> None:
    llm = FakeLLM(["요약입니다."])
    rt = _rt(tmp_path, factory=Factory(llm))
    agent = _agent(rt, avoid_topics=("주차",), summary=True)
    meta, sents, done = _split(list(iter_turn(rt, agent, text=Q_PARK)))
    assert meta.answer_kind == done.answer_kind == "avoided"
    assert meta.candidates == []
    assert [s.text for s in sents] == [AVOIDED_TEXT]
    assert sents[0].supported is False and sents[0].evidence == ()
    assert llm.calls == [] and done.summary_used is False


def test_unknown_has_no_llm(tmp_path: Path) -> None:
    llm = FakeLLM(["요약입니다."])
    factory = Factory(llm)
    rt = _rt(tmp_path, factory=factory)
    meta, sents, done = _split(list(iter_turn(rt, _agent(rt, summary=True), text=Q_NONE)))
    assert meta.answer_kind == "unknown"
    assert [s.text for s in sents] == [UNKNOWN_TEXT]
    assert llm.calls == [] and factory.prompts == [] and done.summary_used is False


def test_unknown_handoff_message(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    agent = _agent(rt, when_unknown="handoff", handoff_message="1번 창구로 가 주세요.")
    _, sents, _ = _split(list(iter_turn(rt, agent, text=Q_NONE)))
    assert [s.text for s in sents] == ["1번 창구로 가 주세요."]


def test_summary_uses_llm_with_persona_prompt(tmp_path: Path) -> None:
    tts = SpyTTS()
    llm = FakeLLM(["주차장은 지하 1층입니다.", "2시간 무료입니다.", "그 뒤는 유료입니다."], tts)
    factory = Factory(llm)
    rt = _rt(tmp_path, tts=tts, factory=factory)
    agent = _agent(rt, summary=True, persona_name="주차도우미", answer_length="short")
    meta, sents, done = _split(list(iter_turn(rt, agent, text=Q_PARK)))
    assert done.summary_used is True
    assert "주차도우미" in factory.prompts[0]
    query, ctx = llm.calls[0]
    assert query == Q_PARK
    assert ctx[0] == FaqItem(id="q-001", question="주차 가능한가요?", answer=PARKING, source="faq_csv")
    assert [s.text for s in sents] == [FRIENDLY_PREFIX + "주차장은 지하 1층입니다.", "2시간 무료입니다."]
    assert meta.sentence_count == 2
    # 첫 문장 TTS는 LLM이 둘째 문장을 내기 전에 이미 시작됐다 (ADR-007)
    assert llm.tts_before_second is True
    assert tts.texts == [s.text for s in sents]


def test_summary_empty_llm_falls_back_to_chunk(tmp_path: Path) -> None:
    rt = _rt(tmp_path, factory=Factory(FakeLLM(["  "])))
    _, sents, done = _split(list(iter_turn(rt, _agent(rt, summary=True), text=Q_PARK)))
    assert sents[0].text == FRIENDLY_PREFIX + "건물 지하 1층에 주차장이 있습니다."
    assert done.summary_used is False


def test_summary_without_factory_uses_chunk(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    assert rt.llm_factory is None
    _, sents, done = _split(list(iter_turn(rt, _agent(rt, summary=True), text=Q_PARK)))
    assert done.summary_used is False
    assert sents[0].text == FRIENDLY_PREFIX + "건물 지하 1층에 주차장이 있습니다."


@pytest.mark.parametrize("voice", list(VOICE_STYLE))
def test_tts_for_called_with_agent_voice(tmp_path: Path, voice: str,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    rt = _rt(tmp_path)
    seen: list[str] = []
    orig = rt.tts_for

    def spy(v: str) -> Any:
        seen.append(v)
        return orig(v)

    monkeypatch.setattr(rt, "tts_for", spy)
    list(iter_turn(rt, _agent(rt, voice=voice), text=Q_PARK))
    assert seen == [voice]


def test_empty_transcript_raises_no_speech(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    with pytest.raises(NoSpeechError):
        next(iter_turn(rt, _agent(rt), text="   "))


def test_audio_decode_error_propagates(tmp_path: Path) -> None:
    class BadSTT:
        def transcribe(self, audio: bytes | None, text_hint: str | None) -> str:
            raise AudioDecodeError("bad")

    rt = _rt(tmp_path, stt=BadSTT())
    with pytest.raises(AudioDecodeError):
        next(iter_turn(rt, _agent(rt), audio=b"xx"))


# --- 목소리 -------------------------------------------------------------------------

class VoiceTTS:
    def __init__(self, style: str = "F1", known: tuple[str, ...] = ("F1", "M1")) -> None:
        self.style, self.known = style, known
        self.loads: list[str] = []

    def synthesize(self, text: str) -> bytes:
        return self.style.encode()

    def for_voice(self, voice: str) -> "VoiceTTS":
        self.loads.append(voice)
        if voice not in self.known:
            raise ValueError(voice)
        return VoiceTTS(voice, self.known)


def test_tts_for_maps_styles_and_falls_back(tmp_path: Path) -> None:
    base = VoiceTTS()
    rt = _rt(tmp_path, tts=base)
    assert rt.tts_for("calm_male").synthesize("x") == b"M1"
    assert rt.tts_for("calm_male") is rt.tts_for("calm_male")
    assert rt.voice_available("calm_male") is True
    assert rt.voice_available("bright_female") is False
    assert rt.tts_for("bright_female").synthesize("x") == b"F1"
    assert rt.voice_available("nope") is False
    assert base.loads.count("F2") == 1  # 없는 목소리도 한 번만 시도한다


def test_stub_tts_ignores_voice(tmp_path: Path) -> None:
    tts = SilentTTS()
    rt = _rt(tmp_path, tts=tts)
    assert rt.tts_for("deep_male") is tts
    assert rt.voice_available("deep_male") is True
    assert rt.voice_capable is False


def test_supertonic_for_voice_shares_model() -> None:
    class FakeModel:
        def get_voice_style(self, voice_name: str) -> str:
            if voice_name != "M1":
                raise FileNotFoundError(voice_name)
            return "style-M1"

    tts = object.__new__(SupertonicTTS)
    tts.lang, tts.total_steps, tts.sample_rate = "ko", 8, 44100
    tts._tts, tts._style = FakeModel(), "style-F1"
    sib = tts.for_voice("M1")
    assert sib is not tts and sib._tts is tts._tts and sib._style == "style-M1"
    assert (sib.lang, sib.total_steps, sib.sample_rate) == ("ko", 8, 44100)
    assert tts._style == "style-F1"
    with pytest.raises(ValueError):
        tts.for_voice("ZZ")


# --- 런타임 -------------------------------------------------------------------------

def test_build_runtime_loads_presets_and_qwen_factory(tmp_path: Path) -> None:
    s = Settings(_env_file=None, presets_dir=ROOT / "data" / "presets", llm_backend="qwen",  # type: ignore[call-arg]
                 llm_api_key="k")
    rt = build_agent_runtime(s, PassthroughSTT(), SilentTTS())
    assert rt.presets[0].preset_id == "civil-kiosk" and len(rt.presets) == 4
    assert rt.store.get("preset-civil-kiosk").preset_id == "civil-kiosk"
    assert rt.store.live_count() == 0
    assert rt.llm_factory is not None
    llm = rt.llm_factory("PROMPT")
    assert isinstance(llm, QwenLLM) and llm._system_prompt == "PROMPT"
    assert rt.limits is s and rt.gate.running == 0


def test_build_runtime_no_key_no_factory(tmp_path: Path) -> None:
    s = _settings(tmp_path).model_copy(update={"llm_backend": "qwen", "llm_api_key": ""})
    assert build_agent_runtime(s, PassthroughSTT(), SilentTTS()).llm_factory is None


def test_voice_capable_with_real_like_backends(tmp_path: Path) -> None:
    rt = _rt(tmp_path, stt=FixedSTT("x"), tts=SpyTTS())
    assert rt.voice_capable is True


def test_index_cache_and_prune(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    a, b = _agent(rt), _agent(rt)
    ia = rt.index_for(a)
    assert rt.index_for(a) is ia
    rt.index_for(b)
    rt.store.delete(a.agent_id)
    rt.index_for(b)
    assert a.agent_id not in rt._indexes and b.agent_id in rt._indexes


def test_qwen_system_prompt_default_and_custom() -> None:
    op = _SpyOpener()
    QwenLLM("k", "http://fake/v1", "m", 1.0, opener=op).answer("q", [_FAQ])
    QwenLLM("k", "http://fake/v1", "m", 1.0, opener=op, system_prompt="SP").answer("q", [_FAQ])
    systems = [json.loads(r.data)["messages"][0]["content"] for r in op.requests]  # type: ignore[arg-type]
    assert systems == [SYSTEM_PROMPT, "SP"]


# --- 개인정보 -----------------------------------------------------------------------

_FAQ = FaqItem(id="q-001", question="주차?", answer=PARKING, source="faq_csv")


def _sse(text: str) -> bytes:
    payload = {"choices": [{"delta": {"content": text}}]}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\ndata: [DONE]\n\n".encode()


class _SpyOpener:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.requests: list[urllib.request.Request] = []

    def __call__(self, req: urllib.request.Request, timeout: float) -> IO[bytes]:
        self.requests.append(req)
        if self.fail:
            raise OSError("down")
        return io.BytesIO(_sse("주차장은 지하 1층에 있습니다. 방문객은 2시간 무료입니다."))


def _qwen_factory(op: _SpyOpener) -> Any:
    def make(prompt: str) -> SentenceStreamingLLM:
        return QwenLLM("k", "http://fake/v1", "m", 1.0, opener=op, system_prompt=prompt)
    return make


def test_privacy_llm_body(tmp_path: Path) -> None:
    op = _SpyOpener()
    stt = FixedSTT(Q_PARK)
    rt = _rt(tmp_path, stt=stt, factory=_qwen_factory(op))
    audio = b"RIFF\x00\x00\x00\x00WAVEfmt audio-bytes"
    events = list(iter_turn(rt, _agent(rt, summary=True), audio=audio))
    assert stt.audio == [audio]
    assert isinstance(events[-1], TurnDone) and events[-1].summary_used is True
    assert len(op.requests) == 1
    raw = op.requests[0].data
    assert isinstance(raw, bytes)
    body = raw.decode("utf-8")
    assert Q_PARK in body and PARKING in body
    assert "audio" not in body.lower() and "b64" not in body.lower()
    assert "RIFF" not in body


def test_privacy_logs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    for op in (_SpyOpener(), _SpyOpener(fail=True)):
        rt = _rt(tmp_path, factory=_qwen_factory(op))
        list(iter_turn(rt, _agent(rt, summary=True), text=Q_PARK))
        list(iter_turn(rt, _agent(rt), text=Q_PARK))
        list(iter_turn(rt, _agent(rt), text=Q_NONE))
        list(iter_turn(rt, _agent(rt, avoid_topics=("주차",)), text=Q_PARK))
    assert "주차 돼요" not in caplog.text
    assert "환불" not in caplog.text
    assert "주차장" not in caplog.text


SAMPLES = ROOT / "data" / "samples"


def _sample_agent(rt: AgentRuntime, kind: str) -> Agent:
    from app.agents.knowledge import chunk_text, parse_faq_csv

    raw = (SAMPLES / f"fitness-center.{kind}").read_text(encoding="utf-8")
    chunks = chunk_text(raw, 100_000)[0] if kind == "txt" else parse_faq_csv(raw, 300, 100_000)[0]
    return rt.store.create("피트니스", AgentSettings(), tuple(chunks))


def test_fitness_text_cancel_sentence_first(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    meta, sents, _ = _split(list(iter_turn(rt, _sample_agent(rt, "txt"), text="PT 당일 취소하면 어떻게 돼요?")))
    assert meta.answer_kind == "grounded"
    assert meta.candidates[0].chunk.title == "개인 트레이닝"
    assert "당일 취소하면 1회가 차감됩니다" in sents[0].text
    assert sents[0].supported is True


def test_fitness_csv_pool_is_single_unknown(tmp_path: Path) -> None:
    rt = _rt(tmp_path)
    meta, sents, _ = _split(list(iter_turn(rt, _sample_agent(rt, "csv"), text="수영장 있어요?")))
    assert meta.answer_kind == "unknown"
    assert [s.text for s in sents] == [UNKNOWN_TEXT]


def test_summary_first_tts_matches_final_prefix_rule(tmp_path: Path) -> None:
    tts = SpyTTS()
    llm = FakeLLM(["요금은 별도입니다.", "주차는 2시간 무료입니다."], tts)
    rt = _rt(tmp_path, tts=tts, factory=Factory(llm))
    _, sents, done = _split(list(iter_turn(rt, _agent(rt, summary=True), text=Q_PARK)))
    assert done.summary_used is True
    assert sents[0].text == "요금은 별도입니다."
    assert tts.texts == [s.text for s in sents]
