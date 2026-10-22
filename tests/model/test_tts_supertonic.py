import pytest

from app.config import Settings
from app.pipeline.runner import build_pipeline
from app.pipeline.tts_supertonic import SupertonicTTS
from app.pipeline.wav import EXPECTED_SAMPLE_RATE, MIN_DURATION_S, MIN_RMS, wav_stats

FAQ001_ANSWER = "주민등록등본은 본인 신분증만 있으면 발급됩니다. 수수료는 1통에 400원입니다."


@pytest.fixture(scope="module")
def tts() -> SupertonicTTS:
    return SupertonicTTS()


def test_faq_answer_is_voiced_wav(tts: SupertonicTTS) -> None:
    s = wav_stats(tts.synthesize(FAQ001_ANSWER))
    assert s.sample_rate == EXPECTED_SAMPLE_RATE
    assert s.channels == 1
    assert s.sample_width == 2
    assert s.duration_s >= MIN_DURATION_S
    assert s.rms > MIN_RMS


def test_longer_text_yields_more_frames(tts: SupertonicTTS) -> None:
    short = wav_stats(tts.synthesize("네."))
    long = wav_stats(tts.synthesize("주민등록등본은 본인 신분증만 있으면 발급됩니다. 수수료는 400원입니다."))
    assert long.frames > short.frames


def test_blank_text_returns_short_silence(tts: SupertonicTTS) -> None:
    s = wav_stats(tts.synthesize("   "))
    assert s.duration_s == pytest.approx(0.1, abs=0.01)
    assert s.rms == 0.0


def test_pipeline_tts_ms_within_budget() -> None:
    pipeline = build_pipeline(Settings(tts_backend="supertonic"))
    result = pipeline.run("주민등록등본 떼려면 뭐 필요해요?")
    assert 0 < result.timings["tts_ms"] < 3000


def test_sample_rate_attribute(tts: SupertonicTTS) -> None:
    assert tts.sample_rate == EXPECTED_SAMPLE_RATE
