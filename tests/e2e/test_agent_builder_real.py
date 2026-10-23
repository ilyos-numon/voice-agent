import base64
import json
from pathlib import Path

import httpx
import pytest

from tests.e2e.conftest import BASE_URL

FIXTURE_WAV = Path(__file__).resolve().parents[1] / "fixtures" / "ask_faq001_ko.wav"
TIMEOUT = 180

# full 모드(음성 인식·합성 실제 모델)가 아니면 파일 전체를 건너뛴다.
_options = httpx.get(f"{BASE_URL}/api/options", timeout=30).json()
pytestmark = pytest.mark.skipif(
    not _options.get("voice_input_available"), reason="full 모드(음성 모델)가 아니면 건너뜀"
)


def _parse_sse(raw: str) -> list[tuple[str, dict]]:
    events = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        name, data = "", ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        events.append((name, json.loads(data)))
    return events


def _open_session(agent_id: str) -> str:
    r = httpx.post(f"{BASE_URL}/api/agents/{agent_id}/sessions", timeout=TIMEOUT)
    assert r.status_code == 201
    return r.json()["session_id"]


def test_audio_stream_recognizes_faq001() -> None:
    sid = _open_session("preset-civil-kiosk")
    r = httpx.post(
        f"{BASE_URL}/api/agents/preset-civil-kiosk/turns/audio-stream",
        params={"session_id": sid},
        content=FIXTURE_WAV.read_bytes(),
        headers={"content-type": "audio/wav"},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert "error" not in [n for n, _ in events], events
    meta = next(d for n, d in events if n == "meta")
    assert "등본" in meta["transcript"]
    assert meta["candidates"][0]["chunk_id"] == "faq-001"
    assert meta["timings"]["listen_ms"] > 0


def test_options_voice_input_available() -> None:
    r = httpx.get(f"{BASE_URL}/api/options", timeout=30)
    assert r.json()["voice_input_available"] is True


def test_voices_differ_for_same_sentence() -> None:
    wavs = {}
    for voice in ("calm_female", "calm_male"):
        r = httpx.post(
            f"{BASE_URL}/api/agents",
            json={
                "name": "목소리 비교",
                "knowledge": {"kind": "faq_csv", "csv": "질문,답변\n주차는 어디에 하나요?,지하 1층 주차장을 이용하세요.\n"},
                "settings": {"voice": voice},
            },
            timeout=TIMEOUT,
        )
        assert r.status_code == 201
        agent_id = r.json()["agent_id"]
        try:
            sid = _open_session(agent_id)
            t = httpx.post(
                f"{BASE_URL}/api/agents/{agent_id}/turns/stream",
                json={"session_id": sid, "text": "주차는 어디에 하나요?"},
                timeout=TIMEOUT,
            )
            assert t.status_code == 200
            sentence = next(d for n, d in _parse_sse(t.text) if n == "sentence")
            wavs[voice] = base64.b64decode(sentence["audio_wav_b64"])
        finally:
            httpx.delete(f"{BASE_URL}/api/agents/{agent_id}", timeout=30)
    assert wavs["calm_female"][:4] == b"RIFF"
    assert wavs["calm_female"] != wavs["calm_male"]


def test_scorecard_voice_channel() -> None:
    import time

    r = httpx.post(
        f"{BASE_URL}/api/agents/preset-restaurant/scorecards", json={"n": 10, "voice": True}, timeout=TIMEOUT
    )
    assert r.status_code in (202, 409), r.text
    job_id = r.json()["job_id"] if r.status_code == 202 else r.json()["detail"]["job_id"]
    deadline = time.monotonic() + 600
    job: dict = {}
    while time.monotonic() < deadline:
        job = httpx.get(f"{BASE_URL}/api/scorecards/{job_id}", timeout=30).json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(2)
    assert job["status"] == "done", job
    report = job["report"]
    assert report["voice"] is not None
    assert report["first_audio_basis"] == "voice"
    assert report["first_audio_ms"]["p50"] > 0
