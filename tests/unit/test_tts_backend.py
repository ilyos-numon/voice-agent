import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.pipeline.runner import build_pipeline, build_tts
from app.pipeline.stubs import SilentTTS

FAQ_PATH = Path(__file__).resolve().parents[2] / "data" / "faq" / "sample_faq.json"


def test_default_backend_is_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TTS_BACKEND", raising=False)
    assert Settings(_env_file=None).tts_backend == "stub"  # type: ignore[call-arg]


def test_build_tts_stub_returns_silent() -> None:
    assert isinstance(build_tts(Settings(tts_backend="stub")), SilentTTS)


def test_build_tts_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown TTS_BACKEND: nope"):
        build_tts(Settings(tts_backend="nope"))


def test_stub_pipeline_does_not_import_supertonic() -> None:
    build_pipeline(Settings(tts_backend="stub", faq_path=FAQ_PATH))
    assert "supertonic" not in sys.modules
