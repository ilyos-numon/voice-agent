from pathlib import Path

import pytest

from app.config import Settings
from app.pipeline.audio import NoSpeechError
from app.pipeline.runner import Pipeline, build_pipeline
from app.pipeline.stream import AudioEvent, DoneEvent, MetaEvent, iter_ask
from app.pipeline.stubs import FALLBACK_ANSWER

FAQ_PATH = Path(__file__).resolve().parents[2] / "data" / "faq" / "sample_faq.json"
DONE_KEYS = {"stt_ms", "retrieve_ms", "llm_ms", "tts_ms", "first_audio_ms", "total_ms"}
Q = "주민등록등본 떼려면 뭐 필요해요?"


@pytest.fixture
def pipeline() -> Pipeline:
    return build_pipeline(Settings(pipeline_mode="stub", faq_path=FAQ_PATH))


def test_event_order_meta_audio_done(pipeline: Pipeline) -> None:
    ev = list(iter_ask(pipeline, text=Q))
    assert isinstance(ev[0], MetaEvent)
    assert isinstance(ev[-1], DoneEvent)
    audios = ev[1:-1]
    assert audios and all(isinstance(a, AudioEvent) for a in audios)
    assert [a.index for a in audios if isinstance(a, AudioEvent)] == list(range(len(audios)))
    assert ev[0].sentence_count == len(audios) == ev[-1].sentence_count


def test_meta_matches_pipeline_run(pipeline: Pipeline) -> None:
    meta = next(iter(iter_ask(pipeline, text=Q)))
    assert isinstance(meta, MetaEvent)
    result = pipeline.run(Q)
    assert meta.transcript == result.transcript
    assert meta.answer == result.answer
    assert meta.source == result.source
    assert set(meta.timings) == {"stt_ms", "retrieve_ms", "llm_ms"}


def test_audio_texts_join_to_answer(pipeline: Pipeline) -> None:
    ev = list(iter_ask(pipeline, text=Q))
    meta = ev[0]
    assert isinstance(meta, MetaEvent)
    texts = [e.text for e in ev if isinstance(e, AudioEvent)]
    assert "".join(texts).replace(" ", "") == meta.answer.replace(" ", "")
    for e in ev:
        if isinstance(e, AudioEvent):
            assert e.audio_wav[:4] == b"RIFF"


def test_done_timings(pipeline: Pipeline) -> None:
    ev = list(iter_ask(pipeline, text=Q))
    done = ev[-1]
    assert isinstance(done, DoneEvent)
    assert set(done.timings) == DONE_KEYS
    assert all(isinstance(v, float) for v in done.timings.values())
    assert 0 < done.timings["first_audio_ms"] <= done.timings["total_ms"]
    first = ev[1]
    assert isinstance(first, AudioEvent)
    assert first.elapsed_ms == done.timings["first_audio_ms"]


def test_elapsed_monotonic(pipeline: Pipeline) -> None:
    audios = [e for e in iter_ask(pipeline, text=Q) if isinstance(e, AudioEvent)]
    elapsed = [a.elapsed_ms for a in audios]
    assert elapsed == sorted(elapsed)


def test_fallback_answer_single_event(pipeline: Pipeline) -> None:
    ev = list(iter_ask(pipeline, text="xyzzy"))
    meta = ev[0]
    assert isinstance(meta, MetaEvent)
    assert meta.source is None and meta.answer == FALLBACK_ANSWER
    assert meta.sentence_count >= 1


def test_blank_transcript_raises_no_speech(pipeline: Pipeline) -> None:
    with pytest.raises(NoSpeechError):
        list(iter_ask(pipeline, text="   "))


def test_stt_exception_propagates(pipeline: Pipeline) -> None:
    class BoomSTT:
        def transcribe(self, audio: bytes | None, text_hint: str | None) -> str:
            raise NoSpeechError("boom")

    p = Pipeline(BoomSTT(), pipeline.retriever, pipeline.llm, pipeline.tts)
    with pytest.raises(NoSpeechError, match="boom"):
        list(iter_ask(p, audio=b"x"))
