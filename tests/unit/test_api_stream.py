import base64
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.schemas import StreamErrorOut
from app.api.stream import format_sse, stream_router
from app.config import Settings
from app.pipeline.audio import AudioDecodeError
from app.pipeline.runner import build_pipeline
from app.pipeline.stubs import SilentTTS

FAQ_PATH = Path(__file__).resolve().parents[2] / "data" / "faq" / "sample_faq.json"
DONE_KEYS = {"stt_ms", "retrieve_ms", "llm_ms", "tts_ms", "first_audio_ms", "total_ms"}
HEADERS = {"content-type": "audio/wav"}
Q = "주민등록등본 떼려면 뭐 필요해요?"


class RaisingSTT:
    def transcribe(self, audio: bytes | None, text_hint: str | None) -> str:
        raise AudioDecodeError("audio decode failed")


@pytest.fixture
def app() -> FastAPI:
    a = FastAPI()
    a.include_router(stream_router)
    a.state.pipeline = build_pipeline(Settings(pipeline_mode="stub", faq_path=FAQ_PATH))
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def parse_sse(raw: str) -> list[tuple[str, dict[str, object]]]:
    out: list[tuple[str, dict[str, object]]] = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        lines = block.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("event: ") and lines[1].startswith("data: ")
        out.append((lines[0][7:], json.loads(lines[1][6:])))
    return out


def test_format_sse_wire() -> None:
    raw = format_sse("error", StreamErrorOut(detail="무음"))
    assert raw == 'event: error\ndata: {"detail":"무음"}\n\n'.encode()


def test_ask_stream_order_and_headers(client: TestClient) -> None:
    res = client.post("/api/ask-stream", json={"text": Q})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert res.headers["cache-control"] == "no-cache"
    assert res.headers["x-accel-buffering"] == "no"
    events = parse_sse(res.text)
    names = [e[0] for e in events]
    assert names[0] == "meta" and names[-1] == "done"
    audios = [d for n, d in events[1:-1] if n == "audio"]
    assert len(audios) == len(events) - 2
    meta, done = events[0][1], events[-1][1]
    assert meta["sentence_count"] == len(audios) == done["sentence_count"]
    assert [a["index"] for a in audios] == list(range(len(audios)))
    assert meta["transcript"] == Q
    assert set(meta["timings"]) == {"stt_ms", "retrieve_ms", "llm_ms"}  # type: ignore[arg-type]
    for a in audios:
        assert base64.b64decode(str(a["audio_wav_b64"]))[:4] == b"RIFF"
    timings = done["timings"]
    assert isinstance(timings, dict) and set(timings) == DONE_KEYS
    assert timings["first_audio_ms"] == audios[0]["elapsed_ms"]


def test_ask_stream_blank_422(client: TestClient) -> None:
    assert client.post("/api/ask-stream", json={"text": "   "}).status_code == 422


def test_ask_audio_stream_validation(client: TestClient) -> None:
    assert client.post("/api/ask-audio-stream", content=b"", headers=HEADERS).status_code == 400
    assert client.post("/api/ask-audio-stream", content=b"hello " * 100, headers=HEADERS).status_code == 415
    big = b"RIFF" + b"\x00" * (10 * 1024 * 1024)
    assert client.post("/api/ask-audio-stream", content=big, headers=HEADERS).status_code == 413


def test_ask_audio_stream_no_speech_error_event(client: TestClient) -> None:
    res = client.post("/api/ask-audio-stream", content=SilentTTS().synthesize("x"), headers=HEADERS)
    assert res.status_code == 200
    assert parse_sse(res.text) == [("error", {"detail": "no speech recognized"})]


def test_ask_audio_stream_decode_error_event(app: FastAPI, client: TestClient) -> None:
    app.state.pipeline.stt = RaisingSTT()
    res = client.post("/api/ask-audio-stream", content=SilentTTS().synthesize("x"), headers=HEADERS)
    assert res.status_code == 200
    assert parse_sse(res.text) == [("error", {"detail": "audio decode failed"})]
