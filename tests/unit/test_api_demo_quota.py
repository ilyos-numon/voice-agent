"""데모 한도 차감·환불 (PLAN §4.5): 실제 create_app 을 데모 env 로 띄워 확인한다."""

import io
import math
import os
import struct
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api.agents as agents_api
from app.agents.limits import Busy
from app.config import get_settings
from app.main import create_app
from app.pipeline.audio import AudioDecodeError

ROOT = Path(__file__).resolve().parents[2]
PRESET = "preset-civil-kiosk"
MISSING_AGENT = "ag_000000000000"
ENV_KEYS = (
    "PIPELINE_MODE",
    "STT_BACKEND",
    "TTS_BACKEND",
    "RETRIEVER_BACKEND",
    "AGENT_SUMMARY_DEFAULT",
    "TURN_CONCURRENCY",
    "TURN_QUEUE_MAX",
    "MAX_AGENTS",
)


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    # get_settings() 가 저장소의 .env 를 읽지 않도록 빈 임시 폴더에서 돌린다.
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith("DEMO_") or key in ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_BACKEND", "stub")
    monkeypatch.setenv("PRESETS_DIR", str(ROOT / "data" / "presets"))
    monkeypatch.setenv("FAQ_PATH", str(ROOT / "data" / "faq" / "sample_faq.json"))
    # 스텁 환경(av 없음)과 같게: 음성 초는 바이트로 추정한다. av 를 import 하면 다른 테스트가 깨진다.
    monkeypatch.setattr(agents_api, "decode_audio", _no_av)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _no_av(data: bytes, sample_rate: int = 16000) -> Any:
    raise ImportError("av")


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    clients: list[TestClient] = []

    def _make(**env: str) -> TestClient:
        base = {"DEMO_MODE": "1", "DEMO_BOT_GUARD": "0", "DEMO_RATE_PER_MINUTE": "1000"}
        for key, value in {**base, **env}.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        client = TestClient(create_app())
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def _remaining(client: TestClient) -> dict[str, int]:
    res = client.get("/api/demo")
    assert res.status_code == 200
    remaining: dict[str, int] = res.json()["remaining"]
    return remaining


def _session(client: TestClient, agent_id: str = PRESET) -> str:
    res = client.post(f"/api/agents/{agent_id}/sessions")
    assert res.status_code == 201
    sid: str = res.json()["session_id"]
    return sid


def _turn(client: TestClient, sid: str, headers: dict[str, str] | None = None) -> Any:
    return client.post(
        f"/api/agents/{PRESET}/turns/stream",
        json={"session_id": sid, "text": "주민등록등본은 어떻게 떼나요?"},
        headers=headers or {},
    )


def _wav(seconds: float) -> bytes:
    rate = 16000
    n = int(rate * seconds)
    frames = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(n)
    )
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return buf.getvalue()


def _audio(client: TestClient, sid: str, body: bytes) -> Any:
    return client.post(
        f"/api/agents/{PRESET}/turns/audio-stream",
        params={"session_id": sid},
        content=body,
        headers={"Content-Type": "audio/wav"},
    )


def test_turn_limit_429_after_three(make_client: Any) -> None:
    client = make_client(DEMO_DAILY_TURNS="3")
    sid = _session(client)
    for _ in range(3):
        assert _turn(client, sid).status_code == 200
    res = _turn(client, sid)
    assert res.status_code == 429
    detail = res.json()["detail"]
    assert detail["code"] == "demo_quota_exceeded"
    assert detail["kind"] == "turns"
    assert detail["reset_at"].endswith("T00:00:00Z")
    assert _remaining(client)["turns"] == 0


def test_global_cap_503(make_client: Any) -> None:
    client = make_client(DEMO_DAILY_TURNS="5", DEMO_GLOBAL_DAILY_TURNS="1")
    sid = _session(client)
    assert _turn(client, sid).status_code == 200
    res = _turn(client, sid)
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "demo_daily_cap"
    assert res.json()["detail"]["kind"] == "turns"
    assert _remaining(client)["turns"] == 4


def test_busy_refunds_turn(make_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(DEMO_DAILY_TURNS="3")
    sid = _session(client)

    def _full(allow_overflow: bool = False) -> Any:
        raise Busy()

    monkeypatch.setattr(client.app.state.agents.gate, "enter", _full)  # type: ignore[attr-defined]
    res = _turn(client, sid)
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "busy"
    assert _remaining(client)["turns"] == 3


def test_session_not_found_refunds_turn(make_client: Any) -> None:
    client = make_client(DEMO_DAILY_TURNS="3")
    res = _turn(client, "s_missing")
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "session_not_found"
    assert _remaining(client)["turns"] == 3


def test_compare_charges_two_turns(make_client: Any) -> None:
    client = make_client(DEMO_DAILY_TURNS="5")
    sid = _session(client)
    res = client.post(
        f"/api/agents/{PRESET}/compare",
        json={"session_id": sid, "question": "주민등록등본은 어떻게 떼나요?", "a": {}, "b": {"tone": "concise"}},
    )
    assert res.status_code == 200
    assert _remaining(client)["turns"] == 3


def test_compare_session_not_found_refunds(make_client: Any) -> None:
    client = make_client(DEMO_DAILY_TURNS="5")
    res = client.post(f"/api/agents/{PRESET}/compare", json={"session_id": "s_missing", "question": "주차"})
    assert res.status_code == 404
    assert _remaining(client)["turns"] == 5


def test_audio_seconds_charged_byte_estimate(make_client: Any) -> None:
    client = make_client(DEMO_DAILY_TURNS="5")
    before = _remaining(client)
    body = _wav(2.5)
    sid = _session(client)
    assert _audio(client, sid, body).status_code == 200
    after = _remaining(client)
    assert before["audio_seconds"] - after["audio_seconds"] == math.ceil(len(body) / 32000) == 3
    assert after["turns"] == before["turns"] - 1


def test_audio_over_20_seconds_413_no_charge(make_client: Any) -> None:
    client = make_client(DEMO_DAILY_TURNS="5")
    before = _remaining(client)
    sid = _session(client)
    res = _audio(client, sid, _wav(25))
    assert res.status_code == 413
    assert res.json()["detail"]["code"] == "audio_too_large"
    assert _remaining(client) == before


def test_audio_decode_error_charges_turn_only(make_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def _bad(data: bytes, sample_rate: int = 16000) -> Any:
        raise AudioDecodeError("bad")

    monkeypatch.setattr(agents_api, "decode_audio", _bad)
    client = make_client(DEMO_DAILY_TURNS="5")
    before = _remaining(client)
    sid = _session(client)
    assert _audio(client, sid, _wav(2.5)).status_code == 200
    after = _remaining(client)
    assert after["audio_seconds"] == before["audio_seconds"]
    assert after["turns"] == before["turns"] - 1


def test_audio_session_not_found_refunds_both(make_client: Any) -> None:
    client = make_client(DEMO_DAILY_TURNS="5")
    before = _remaining(client)
    res = _audio(client, "s_missing", _wav(2.5))
    assert res.status_code == 404
    assert _remaining(client) == before


def test_create_agent_charges_and_refunds_on_failure(make_client: Any) -> None:
    client = make_client(DEMO_DAILY_AGENTS="2")
    res = client.post("/api/agents", json={"name": "빈 상담원", "knowledge": {"kind": "text", "text": "   "}})
    assert res.status_code == 400
    assert _remaining(client)["agents"] == 2
    ok = client.post(
        "/api/agents",
        json={"name": "헬스장", "knowledge": {"kind": "text", "text": "영업시간은 매일 오전 6시부터 밤 11시까지입니다."}},
    )
    assert ok.status_code == 201
    assert _remaining(client)["agents"] == 1


def test_create_agent_capacity_full_refunds(make_client: Any) -> None:
    client = make_client(DEMO_DAILY_AGENTS="2", MAX_AGENTS="0")
    res = client.post(
        "/api/agents", json={"name": "헬스장", "knowledge": {"kind": "text", "text": "영업시간은 매일 오전 6시입니다."}}
    )
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "capacity_full"
    assert _remaining(client)["agents"] == 2


def test_scorecard_agent_not_found_refunds(make_client: Any) -> None:
    client = make_client()
    res = client.post(f"/api/agents/{MISSING_AGENT}/scorecards", json={"n": 10})
    assert res.status_code == 404
    assert _remaining(client)["scorecards"] == 2


def test_scorecard_charged(make_client: Any) -> None:
    client = make_client()
    res = client.post(f"/api/agents/{PRESET}/scorecards", json={"n": 10})
    assert res.status_code == 202
    assert _remaining(client)["scorecards"] == 1


def test_demo_off_no_charge(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        assert client.app.state.demo_quota is None  # type: ignore[attr-defined]
        sid = _session(client)
        for _ in range(12):
            assert _turn(client, sid).status_code == 200
        demo = client.get("/api/demo").json()
        assert demo["demo_mode"] is False
        assert demo["remaining"] is None


def test_bot_guard_token_required_then_ok(make_client: Any) -> None:
    client = make_client(DEMO_BOT_GUARD="1", DEMO_DAILY_TURNS="3")
    sid = _session(client)
    res = _turn(client, sid)
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "demo_token_required"
    demo = client.get("/api/demo").json()
    assert demo["remaining"]["turns"] == 3
    ok = _turn(client, sid, headers={"X-Demo-Token": demo["token"]})
    assert ok.status_code == 200
    assert _remaining(client)["turns"] == 2
