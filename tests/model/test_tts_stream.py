import json
from pathlib import Path

import pytest

from app.config import Settings
from app.pipeline.runner import build_pipeline
from app.pipeline.stream import AudioEvent, DoneEvent, iter_ask
from app.pipeline.tts_supertonic import SupertonicTTS
from app.pipeline.wav import wav_stats

LONG_ID = "faq-020"
LONG_QUESTION = "위반건축물 행정처분"
FAQ_PATH = Path("data/faq/faq.jsonl")


def _long_answer() -> str:
    for line in FAQ_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row["id"] == LONG_ID:
                return row["answer"]
    raise AssertionError(f"{LONG_ID} not found")


@pytest.fixture(scope="module")
def pipeline():
    return build_pipeline(
        Settings(tts_backend="supertonic", retriever_backend="bm25", faq_path=FAQ_PATH)
    )


@pytest.fixture(scope="module")
def events(pipeline) -> list:
    pipeline.tts.synthesize("안녕하세요")
    return list(iter_ask(pipeline, text=LONG_QUESTION))


def test_first_audio_under_half_of_full_tts(pipeline, events) -> None:
    answer = _long_answer()
    tts: SupertonicTTS = pipeline.tts
    tts.synthesize("안녕하세요")
    import time

    t0 = time.perf_counter()
    tts.synthesize(answer)
    a = (time.perf_counter() - t0) * 1000
    done = events[-1]
    assert isinstance(done, DoneEvent)
    b = done.timings["first_audio_ms"]
    ratio = b / a
    print(f"full_tts_ms={a:.1f} first_audio_ms={b:.1f} ratio={ratio:.3f} sentences={done.sentence_count}")
    assert done.sentence_count >= 4
    assert b < 3000
    assert ratio < 0.5


def test_every_sentence_wav_is_voiced(events) -> None:
    audios = [e for e in events if isinstance(e, AudioEvent)]
    assert len(audios) >= 4
    for e in audios:
        s = wav_stats(e.audio_wav)
        assert s.rms > 200, (e.index, s.rms)
        assert s.duration_s >= 0.3, (e.index, s.duration_s)
