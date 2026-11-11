import base64

import httpx

TIMING_KEYS = ["stt_ms", "retrieve_ms", "llm_ms", "tts_ms", "total_ms"]


def test_ask_success(base_url: str) -> None:
    r = httpx.post(
        f"{base_url}/api/ask", json={"text": "주민등록등본 떼려면 뭐 필요해요?"}, timeout=10
    )
    assert r.status_code == 200
    body = r.json()
    assert body["source"]["id"] == "faq-001"
    for k in TIMING_KEYS:
        assert isinstance(body["timings"][k], float), k
    assert base64.b64decode(body["audio_wav_b64"]).startswith(b"RIFF")


def test_ask_empty_text_422(base_url: str) -> None:
    r = httpx.post(f"{base_url}/api/ask", json={"text": ""}, timeout=5)
    assert r.status_code == 422


def test_ask_unknown_question_no_source(base_url: str) -> None:
    r = httpx.post(f"{base_url}/api/ask", json={"text": "xyzzy"}, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["source"] is None
    assert "찾지 못했습니다" in body["answer"]


def test_ask_missing_body_422(base_url: str) -> None:
    r = httpx.post(f"{base_url}/api/ask", timeout=5)
    assert r.status_code == 422
