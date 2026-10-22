from pathlib import Path

import pytest

from app.config import Settings
from app.pipeline.audio import AudioDecodeError, NoSpeechError
from app.pipeline.runner import build_pipeline
from app.pipeline.stt_whisper import WhisperSTT
from app.pipeline.stubs import KeywordRetriever
from app.pipeline.wav import pcm16_to_wav

FIXTURE_WAV = Path(__file__).resolve().parents[1] / "fixtures" / "ask_faq001_ko.wav"


@pytest.fixture(scope="module")
def stt() -> WhisperSTT:
    return WhisperSTT()


def test_fixture_transcript_contains_deungbon(stt: WhisperSTT) -> None:
    assert "등본" in stt.transcribe(FIXTURE_WAV.read_bytes(), None)


def test_fixture_transcript_retrieves_faq001(stt: WhisperSTT) -> None:
    text = stt.transcribe(FIXTURE_WAV.read_bytes(), None)
    hits = KeywordRetriever(Path("data/faq/sample_faq.json")).search(text)
    assert hits[0].id == "faq-001"


def test_pipeline_audio_end_to_end() -> None:
    pipeline = build_pipeline(Settings(stt_backend="whisper", tts_backend="stub"))
    result = pipeline.run(audio=FIXTURE_WAV.read_bytes())
    assert result.source is not None
    assert result.source.id == "faq-001"
    assert 0 < result.timings["stt_ms"] < 3000


def test_one_second_silence_raises_no_speech(stt: WhisperSTT) -> None:
    wav = pcm16_to_wav(b"\x00\x00" * 16000, 16000)
    with pytest.raises(NoSpeechError):
        stt.transcribe(wav, None)


def test_corrupt_webm_raises_decode_error(stt: WhisperSTT) -> None:
    with pytest.raises(AudioDecodeError):
        stt.transcribe(b"\x1a\x45\xdf\xa3" + bytes(range(256)) * 8, None)


def test_text_path_returns_hint(stt: WhisperSTT) -> None:
    assert stt.transcribe(None, "힌트") == "힌트"
