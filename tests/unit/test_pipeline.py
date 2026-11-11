from pathlib import Path

import pytest

from app.config import Settings
from app.pipeline.runner import Pipeline, build_pipeline
from app.pipeline.stubs import FALLBACK_ANSWER, SilentTTS

FAQ_PATH = Path(__file__).resolve().parents[2] / "data" / "faq" / "sample_faq.json"
TIMING_KEYS = {"stt_ms", "retrieve_ms", "llm_ms", "tts_ms", "total_ms"}


@pytest.fixture
def pipeline() -> Pipeline:
    return build_pipeline(Settings(pipeline_mode="stub", faq_path=FAQ_PATH))


def test_matches_faq_001_with_timings(pipeline: Pipeline) -> None:
    result = pipeline.run("주민등록등본 떼려면 뭐 필요해요?")
    assert result.source is not None and result.source.id == "faq-001"
    assert "신분증" in result.answer
    assert set(result.timings) == TIMING_KEYS
    assert all(isinstance(v, float) for v in result.timings.values())
    assert len(result.audio_wav) > 0


def test_no_match_returns_fallback(pipeline: Pipeline) -> None:
    result = pipeline.run("xyzzy")
    assert result.source is None
    assert result.answer == FALLBACK_ANSWER


def test_silent_tts_wav() -> None:
    wav = SilentTTS().synthesize("x")
    assert len(wav) == 3244
    assert wav[:4] == b"RIFF"


def test_unknown_mode_raises() -> None:
    with pytest.raises(ValueError, match="unknown PIPELINE_MODE: nope"):
        build_pipeline(Settings(pipeline_mode="nope"))
