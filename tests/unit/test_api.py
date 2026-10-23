import base64
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

TIMING_KEYS = {"stt_ms", "retrieve_ms", "llm_ms", "tts_ms", "total_ms"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def test_health(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.text == '{"status":"ok","version":"0.1.0","pipeline_mode":"stub"}'


def test_ask_matches_faq_001(client: TestClient) -> None:
    res = client.post("/api/ask", json={"text": "주민등록등본 떼려면 뭐 필요해요?"})
    assert res.status_code == 200
    body = res.json()
    assert body["source"]["id"] == "faq-001"
    assert set(body["timings"]) == TIMING_KEYS
    assert base64.b64decode(body["audio_wav_b64"])[:4] == b"RIFF"


@pytest.mark.parametrize("payload", [{"text": ""}, {"text": "   "}, {}])
def test_ask_invalid_422(client: TestClient, payload: dict[str, str]) -> None:
    assert client.post("/api/ask", json=payload).status_code == 422


def test_ask_not_json_422(client: TestClient) -> None:
    res = client.post("/api/ask", content=b"not json", headers={"content-type": "application/json"})
    assert res.status_code == 422


def test_index_html(client: TestClient) -> None:
    res = client.get("/static/index.html")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert 'id="timings"' in res.text
