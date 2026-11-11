import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.agents as agents_api
from app.agents.jobs import ScorecardJobs
from app.agents.limits import TurnGate
from app.agents.runtime import AgentRuntime, build_agent_runtime
from app.api.agents import agents_router
from app.config import Settings
from app.pipeline.audio import MAX_AUDIO_BYTES
from app.pipeline.stubs import PassthroughSTT, SilentTTS

ROOT = Path(__file__).resolve().parents[2]
PRESETS = ROOT / "data" / "presets"
WAV = ROOT / "tests" / "fixtures" / "ask_faq001_ko.wav"
CSV = (
    "질문,답변\n"
    "주차는 어디에 하나요?,지하 1층 주차장을 이용하세요. 두 시간 무료입니다. 영수증을 보여 주세요.\n"
    "영업시간이 어떻게 되나요?,매일 오전 10시부터 오후 9시까지 영업합니다.\n"
    "예약은 어떻게 하나요?,전화나 홈페이지에서 예약할 수 있습니다.\n"
    "포장 주문이 되나요?,모든 메뉴를 포장할 수 있습니다. 포장 용기는 무료입니다.\n"
)
DONE_TIMING_KEYS = {"listen_ms", "search_ms", "think_ms", "speak_ms", "first_audio_ms", "total_ms", "queue_ms"}
Q = "주차는 어디에 하나요?"


def make_app(**overrides: Any) -> FastAPI:
    settings = Settings(_env_file=None, llm_backend="stub", presets_dir=PRESETS, **overrides)  # type: ignore[call-arg]
    a = FastAPI()
    a.include_router(agents_router)
    rt = build_agent_runtime(settings, PassthroughSTT(), SilentTTS())
    a.state.agents = rt
    a.state.scorecard_jobs = ScorecardJobs(rt, max_waiting=settings.scorecard_queue_max)
    return a


@pytest.fixture
def app() -> Iterator[FastAPI]:
    a = make_app()
    yield a
    a.state.scorecard_jobs.shutdown()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def rt_of(app: FastAPI) -> AgentRuntime:
    rt: AgentRuntime = app.state.agents
    return rt


def create_agent(client: TestClient, **settings: Any) -> str:
    r = client.post("/api/agents", json={"knowledge": {"kind": "faq_csv", "csv": CSV}, "settings": settings})
    assert r.status_code == 201, r.text
    aid: str = r.json()["agent_id"]
    return aid


def open_session(client: TestClient, agent_id: str) -> str:
    r = client.post(f"/api/agents/{agent_id}/sessions")
    assert r.status_code == 201, r.text
    sid: str = r.json()["session_id"]
    return sid


def parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        lines = block.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("event: ") and lines[1].startswith("data: ")
        out.append((lines[0][7:], json.loads(lines[1][6:])))
    return out


def ask(client: TestClient, aid: str, sid: str, text: str = Q) -> list[tuple[str, dict[str, Any]]]:
    r = client.post(f"/api/agents/{aid}/turns/stream", json={"session_id": sid, "text": text})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    return parse_sse(r.text)


def assert_error(r: Any, status: int, code: str) -> None:
    assert r.status_code == status, r.text
    detail = r.json()["detail"]
    assert detail["code"] == code
    assert detail["message"]


def test_turn_stream_order_and_fields(app: FastAPI, client: TestClient) -> None:
    aid = create_agent(client, answer_length="detailed")
    sid = open_session(client, aid)
    events = ask(client, aid, sid)
    names = [n for n, _ in events]
    meta = events[0][1]
    assert names[0] == "meta"
    n = meta["sentence_count"]
    assert n == 3
    assert names == ["meta"] + ["sentence"] * n + ["done"]
    assert meta["turn_id"].startswith("t_")
    assert meta["transcript"] == Q
    assert meta["answer_kind"] == "grounded"
    assert set(meta["timings"]) == {"listen_ms", "search_ms", "think_ms"}
    cands = meta["candidates"]
    assert 1 <= len(cands) <= 3
    assert cands[0]["chunk_id"] == "q-001" and cands[0]["rank"] == 1
    assert [c["score"] for c in cands] == sorted((c["score"] for c in cands), reverse=True)
    sentences = [d for name, d in events if name == "sentence"]
    assert [s["index"] for s in sentences] == list(range(n))
    first = sentences[0]
    assert set(first) == {"index", "text", "supported", "evidence", "audio_wav_b64", "speak_ms", "elapsed_ms"}
    assert first["text"].startswith("네, ")
    assert first["supported"] is True
    assert first["evidence"][0]["chunk_id"] == "q-001"
    assert set(first["evidence"][0]) == {"chunk_id", "title", "quote", "overlap"}
    done = events[-1][1]
    assert done["turn_id"] == meta["turn_id"]
    assert done["sentence_count"] == n
    assert done["answer_kind"] == "grounded"
    assert done["summary_used"] is False
    assert set(done["timings"]) == DONE_TIMING_KEYS
    assert done["questions_left"] == 29
    assert ask(client, aid, sid)[-1][1]["questions_left"] == 28
    gate = rt_of(app).gate
    assert gate.running == 0 and gate.waiting == 0


def test_avoided_and_unknown_candidates(client: TestClient) -> None:
    aid = create_agent(client, avoid_topics=["주차"])
    sid = open_session(client, aid)
    meta = ask(client, aid, sid)[0][1]
    assert meta["answer_kind"] == "avoided" and meta["candidates"] == []
    meta = ask(client, aid, sid, "우주 정거장 발사 일정 알려 주세요")[0][1]
    assert meta["answer_kind"] == "unknown"
    assert len(meta["candidates"]) <= 3


def test_turn_errors(client: TestClient) -> None:
    aid = create_agent(client)
    sid = open_session(client, aid)
    body = {"session_id": sid, "text": Q}
    assert_error(client.post("/api/agents/ag_000000000000/turns/stream", json=body), 404, "agent_not_found")
    assert_error(client.post(f"/api/agents/{aid}/turns/stream", json={"session_id": "s_x", "text": Q}),
                 404, "session_not_found")
    other = open_session(client, "preset-civil-kiosk")
    assert_error(client.post(f"/api/agents/{aid}/turns/stream", json={"session_id": other, "text": Q}),
                 404, "session_not_found")
    assert client.post(f"/api/agents/{aid}/turns/stream", json={"session_id": sid, "text": "  "}).status_code == 422
    assert client.post(f"/api/agents/{aid}/turns/stream",
                       json={"session_id": sid, "text": "가" * 501}).status_code == 422


def test_question_limit_429() -> None:
    a = make_app(session_max_questions=1)
    try:
        c = TestClient(a)
        aid = create_agent(c)
        sid = open_session(c, aid)
        assert ask(c, aid, sid)[-1][1]["questions_left"] == 0
        assert_error(c.post(f"/api/agents/{aid}/turns/stream", json={"session_id": sid, "text": Q}),
                     429, "question_limit")
    finally:
        a.state.scorecard_jobs.shutdown()


def test_gate_full_sends_queue_first(app: FastAPI, client: TestClient) -> None:
    rt = rt_of(app)
    rt.gate = TurnGate(1, 8)
    aid = create_agent(client)
    sid = open_session(client, aid)
    held = rt.gate.enter()
    timer = threading.Timer(1.3, held.release)
    timer.start()
    try:
        events = ask(client, aid, sid)
    finally:
        timer.cancel()
        held.release()
    names = [n for n, _ in events]
    assert events[0] == ("queue", {"position": 1})
    assert names.count("queue") >= 2  # 대기 중 1초 간격으로 다시 알린다
    rest = [n for n in names if n != "queue"]
    assert rest[0] == "meta" and rest[-1] == "done"
    assert names.index("meta") > max(i for i, n in enumerate(names) if n == "queue")
    assert events[-1][1]["timings"]["queue_ms"] >= 1000.0
    assert rt.gate.running == 0 and rt.gate.waiting == 0


def test_queue_full_503_refunds(app: FastAPI, client: TestClient) -> None:
    rt = rt_of(app)
    rt.gate = TurnGate(1, 1)
    aid = create_agent(client)
    sid = open_session(client, aid)
    running = rt.gate.enter()
    waiting = rt.gate.enter()
    try:
        assert_error(client.post(f"/api/agents/{aid}/turns/stream", json={"session_id": sid, "text": Q}),
                     503, "busy")
    finally:
        waiting.release()
        running.release()
    assert ask(client, aid, sid)[-1][1]["questions_left"] == 29  # 503 때 쓴 질문은 되돌려졌다


def test_internal_error_event_releases_gate(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> Iterator[Any]:
        raise RuntimeError("boom")
        yield  # pragma: no cover

    monkeypatch.setattr(agents_api, "iter_turn", boom)
    aid = create_agent(client)
    sid = open_session(client, aid)
    events = ask(client, aid, sid)
    assert events == [("error", {"code": "internal", "message": events[0][1]["message"]})]
    assert rt_of(app).gate.running == 0


# ---- audio ----


def test_audio_body_checks(client: TestClient) -> None:
    aid = create_agent(client)
    sid = open_session(client, aid)
    url = f"/api/agents/{aid}/turns/audio-stream"
    h = {"content-type": "application/octet-stream"}
    assert_error(client.post(url, params={"session_id": sid}, content=b"", headers=h), 400, "empty_audio")
    assert_error(client.post(url, params={"session_id": sid}, content=b"not audio at all", headers=h),
                 415, "unsupported_audio")
    assert_error(client.post(url, params={"session_id": sid}, content=b"\0" * (MAX_AUDIO_BYTES + 1), headers=h),
                 413, "audio_too_large")
    assert client.post(url, content=WAV.read_bytes(), headers=h).status_code == 422
    assert_error(client.post("/api/agents/ag_000000000000/turns/audio-stream", params={"session_id": sid},
                             content=WAV.read_bytes(), headers=h), 404, "agent_not_found")
    assert_error(client.post(url, params={"session_id": "s_x"}, content=WAV.read_bytes(), headers=h),
                 404, "session_not_found")
    # 형식 검사로 거절한 요청은 질문 수를 쓰지 않는다
    assert ask(client, aid, sid)[-1][1]["questions_left"] == 29


def test_audio_stream_no_speech_with_stub_stt(app: FastAPI, client: TestClient) -> None:
    aid = create_agent(client)
    sid = open_session(client, aid)
    r = client.post(f"/api/agents/{aid}/turns/audio-stream", params={"session_id": sid},
                    content=WAV.read_bytes(), headers={"content-type": "audio/wav"})
    assert r.status_code == 200
    events = parse_sse(r.text)
    assert len(events) == 1
    name, data = events[0]
    assert name == "error" and data["code"] == "no_speech"
    assert rt_of(app).gate.running == 0
