import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.pipeline.runner import build_pipeline, build_stt
from app.pipeline.stubs import PassthroughSTT

FAQ_PATH = Path(__file__).resolve().parents[2] / "data" / "faq" / "sample_faq.json"


def test_default_stt_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("STT_BACKEND", "STT_MODEL", "STT_BEAM_SIZE"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.stt_backend == "stub"
    assert s.stt_model == "small"
    assert s.stt_beam_size == 1


def test_build_stt_stub_returns_passthrough() -> None:
    assert isinstance(build_stt(Settings(stt_backend="stub")), PassthroughSTT)


def test_build_stt_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown STT_BACKEND: nope"):
        build_stt(Settings(stt_backend="nope"))


def test_stub_pipeline_does_not_import_whisper_or_av() -> None:
    build_pipeline(Settings(stt_backend="stub", tts_backend="stub", faq_path=FAQ_PATH))
    assert "faster_whisper" not in sys.modules
    assert "av" not in sys.modules


def test_stub_pipeline_passes_text_through() -> None:
    p = build_pipeline(Settings(stt_backend="stub", tts_backend="stub", faq_path=FAQ_PATH))
    assert p.run("x").transcript == "x"
