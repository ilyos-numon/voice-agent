import base64
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.pipeline.audio import AudioDecodeError
from app.pipeline.stubs import SilentTTS

TIMING_KEYS = {"stt_ms", "retrieve_ms", "llm_ms", "tts_ms", "total_ms"}
HEADERS = {"content-type": "audio/wav"}
QUESTION = "주민등록등본 떼려면 뭐 필요해요?"


class RaisingSTT:
    def transcribe(self, audio: bytes | None, text_hint: str | None) -> str:
        raise AudioDecodeError("audio decode failed")


class FixedSTT:
    def transcribe(self, audio: bytes | None, text_hint: str | None) -> str:
        return QUESTION


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def test_ask_audio_empty_400(client: TestClient) -> None:
    res = client.post("/api/ask-audio", content=b"", headers=HEADERS)
    assert res.status_code == 400
    assert res.json()["detail"] == "empty audio"


def test_ask_audio_garbage_415(client: TestClient) -> None:
    res = client.post("/api/ask-audio", content=b"hello " * 100, headers=HEADERS)
    assert res.status_code == 415
    assert res.json()["detail"] == "unsupported audio format"


def test_ask_audio_too_large_413(client: TestClient) -> None:
    res = client.post("/api/ask-audio", content=b"RIFF" + b"\x00" * (10 * 1024 * 1024), headers=HEADERS)
    assert res.status_code == 413


def test_ask_audio_stub_no_speech_422(client: TestClient) -> None:
    res = client.post("/api/ask-audio", content=SilentTTS().synthesize("x"), headers=HEADERS)
    assert res.status_code == 422
    assert res.json()["detail"] == "no speech recognized"


def test_ask_audio_decode_error_400(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client.app.state.pipeline, "stt", RaisingSTT())  # type: ignore[attr-defined]
    res = client.post("/api/ask-audio", content=SilentTTS().synthesize("x"), headers=HEADERS)
    assert res.status_code == 400
    assert res.json()["detail"] == "audio decode failed"


def test_ask_audio_fake_stt_hits_faq001(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client.app.state.pipeline, "stt", FixedSTT())  # type: ignore[attr-defined]
    res = client.post("/api/ask-audio", content=SilentTTS().synthesize("x"), headers=HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["transcript"] == QUESTION
    assert body["source"]["id"] == "faq-001"
    assert set(body["timings"]) == TIMING_KEYS
    assert base64.b64decode(body["audio_wav_b64"])[:4] == b"RIFF"
