import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.agents.compare as compare_mod
from app.agents.jobs import ScorecardJobs
from app.agents.limits import TurnGate
from app.agents.runtime import AgentRuntime, build_agent_runtime
from app.api.agents import agents_router
from app.config import Settings
from app.pipeline.stubs import PassthroughSTT, SilentTTS

ROOT = Path(__file__).resolve().parents[2]
PRESETS = ROOT / "data" / "presets"
ISO_Z = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
CSV = (
    "질문,답변\n"
    "주차는 어디에 하나요?,지하 1층 주차장을 이용하세요. 두 시간 무료입니다.\n"
    "영업시간이 어떻게 되나요?,매일 오전 10시부터 오후 9시까지 영업합니다.\n"
    "예약은 어떻게 하나요?,전화나 홈페이지에서 예약할 수 있습니다.\n"
    "반려동물 동반이 가능한가요?,테라스 좌석에서만 반려동물과 함께 앉을 수 있습니다.\n"
    "포장 주문이 되나요?,모든 메뉴를 포장할 수 있습니다. 포장 용기는 무료입니다.\n"
    "단체석이 있나요?,최대 20명까지 앉을 수 있는 단체석이 있습니다.\n"
    "주류를 판매하나요?,맥주와 와인을 판매합니다.\n"
    "아이 의자가 있나요?,아이 의자를 다섯 개 준비해 두었습니다.\n"
    "카드 결제가 되나요?,모든 카드로 결제할 수 있습니다.\n"
    "휴무일이 언제인가요?,매주 월요일은 쉽니다.\n"
    "와이파이가 되나요?,매장 안에서 무료 와이파이를 쓸 수 있습니다.\n"
    "배달도 하나요?,배달 앱으로 주문하시면 배달해 드립니다.\n"
)
FORBIDDEN = ("top_k", "temperature", "bm25")


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


def create_csv_agent(client: TestClient, **settings: Any) -> dict[str, Any]:
    r = client.post("/api/agents", json={"name": "가게", "knowledge": {"kind": "faq_csv", "csv": CSV},
                                         "settings": settings})
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


def open_session(client: TestClient, agent_id: str) -> str:
    r = client.post(f"/api/agents/{agent_id}/sessions")
    assert r.status_code == 201, r.text
    sid: str = r.json()["session_id"]
    return sid


def assert_error(r: Any, status: int, code: str) -> dict[str, Any]:
    assert r.status_code == status, r.text
    detail: dict[str, Any] = r.json()["detail"]
    assert detail["code"] == code
    assert isinstance(detail["message"], str) and detail["message"]
    return detail


def walk(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from walk(v)
    else:
        yield str(value)


# ---- options / presets ----


def test_options_shape_and_no_engine_terms(client: TestClient) -> None:
    r = client.get("/api/options")
    assert r.status_code == 200
    body = r.json()
    assert [o["value"] for o in body["answer_length"]] == ["one_sentence", "short", "detailed"]
    assert body["answer_length"][0]["label"] == "한 문장"
    assert [o["value"] for o in body["tone"]] == ["friendly", "concise"]
    assert [o["value"] for o in body["when_unknown"]] == ["say_unknown", "handoff"]
    assert [o["value"] for o in body["voices"]] == ["calm_female", "bright_female", "calm_male", "deep_male"]
    assert all(v["available"] is True for v in body["voices"])
    assert body["defaults"] == {
        "persona_name": "상담원", "tone": "friendly", "voice": "calm_female", "answer_length": "short",
        "when_unknown": "say_unknown", "handoff_message": "담당자에게 문의해 주세요.", "avoid_topics": [],
        "summary": False,
    }
    assert body["limits"] == {
        "max_text_chars": 20000, "max_csv_rows": 300, "max_csv_chars": 100000,
        "max_questions_per_session": 30, "agent_ttl_hours": 24, "max_avoid_topics": 10,
        "max_avoid_topic_chars": 20, "max_persona_name_chars": 20, "max_handoff_message_chars": 100,
        "max_question_chars": 500,
    }
    assert body["summary_available"] is False
    assert body["voice_input_available"] is False
    for token in walk(body):
        low = token.lower()
        assert not any(f in low for f in FORBIDDEN), token


def test_presets_list(client: TestClient) -> None:
    r = client.get("/api/presets")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 4
    assert items[0]["preset_id"] == "civil-kiosk"
    for p in items:
        assert p["agent_id"] == f"preset-{p['preset_id']}"
        assert len(p["sample_questions"]) == 3
        assert p["chunk_count"] > 0
        assert set(p) == {"preset_id", "title", "description", "sample_questions", "agent_id", "chunk_count"}


# ---- create ----


def test_create_text_agent(client: TestClient) -> None:
    text = "주차 안내\n지하 1층 주차장을 이용하세요. 두 시간 무료입니다.\n\n영업 시간\n매일 오전 10시에 엽니다."
    r = client.post("/api/agents", json={"name": "우리 가게 상담원", "knowledge": {"kind": "text", "text": text},
                                         "settings": {"answer_length": "one_sentence"}})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["agent_id"].startswith("ag_") and len(body["agent_id"]) == 15
    assert body["name"] == "우리 가게 상담원"
    assert body["preset_id"] is None
    assert body["settings"]["answer_length"] == "one_sentence"
    assert body["settings"]["tone"] == "friendly"
    assert body["chunk_count"] == 2
    assert body["share_path"] == f"/talk?agent={body['agent_id']}"
    assert body["warnings"] == []
    assert re.match(ISO_Z, body["created_at"]) and re.match(ISO_Z, body["expires_at"])


def test_create_csv_agent_with_warnings(client: TestClient) -> None:
    csv = "질문,답변\n주차 돼요?,지하 1층입니다.\n,빈 질문\n주차 돼요?,중복\n"
    r = client.post("/api/agents", json={"knowledge": {"kind": "faq_csv", "csv": csv}})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "내 상담원"
    assert body["chunk_count"] == 1
    assert [w["code"] for w in body["warnings"]] == ["empty_row", "duplicate_question"]


def test_create_knowledge_errors(client: TestClient) -> None:
    assert_error(client.post("/api/agents", json={"knowledge": {"kind": "text", "text": "  \n "}}),
                 400, "knowledge_empty")
    assert_error(client.post("/api/agents", json={"knowledge": {"kind": "faq_csv", "csv": '"주차,안내\n'}}),
                 400, "knowledge_bad_csv")
    assert_error(client.post("/api/agents", json={"knowledge": {"kind": "text", "text": "가" * 20001}}),
                 413, "knowledge_too_large")


def test_create_validation_422(client: TestClient) -> None:
    kn = {"kind": "text", "text": "주차는 지하 1층입니다."}
    assert client.post("/api/agents", json={"knowledge": kn, "settings": {"tone": "angry"}}).status_code == 422
    assert client.post("/api/agents", json={"knowledge": kn, "settings": {"persona_name": "   "}}).status_code == 422
    assert client.post("/api/agents", json={"knowledge": {"kind": "pdf", "text": "x"}}).status_code == 422
    assert client.post("/api/agents", json={"name": "x" * 31, "knowledge": kn}).status_code == 422


def test_create_capacity_full() -> None:
    a = make_app(max_agents=1)
    try:
        c = TestClient(a)
        kn = {"kind": "text", "text": "주차는 지하 1층입니다."}
        assert c.post("/api/agents", json={"knowledge": kn}).status_code == 201
        assert_error(c.post("/api/agents", json={"knowledge": kn}), 503, "capacity_full")
    finally:
        a.state.scorecard_jobs.shutdown()


# ---- get / patch / delete ----


def test_get_agent_and_preset(client: TestClient) -> None:
    created = create_csv_agent(client)
    r = client.get(f"/api/agents/{created['agent_id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["warnings"] == []
    assert body["chunk_count"] == created["chunk_count"]
    p = client.get("/api/agents/preset-civil-kiosk").json()
    assert p["preset_id"] == "civil-kiosk" and p["expires_at"] is None
    assert_error(client.get("/api/agents/ag_000000000000"), 404, "agent_not_found")


def test_patch_settings(client: TestClient) -> None:
    aid = create_csv_agent(client)["agent_id"]
    r = client.patch(f"/api/agents/{aid}/settings", json={"tone": "concise", "avoid_topics": ["가격"]})
    assert r.status_code == 200, r.text
    s = r.json()["settings"]
    assert s["tone"] == "concise" and s["avoid_topics"] == ["가격"]
    assert s["answer_length"] == "short"
    assert client.get(f"/api/agents/{aid}").json()["settings"]["tone"] == "concise"
    assert client.patch(f"/api/agents/{aid}/settings", json={"top_k": 3}).status_code == 422
    assert client.patch(f"/api/agents/{aid}/settings", json={"avoid_topics": ["a"] * 11}).status_code == 422
    assert_error(client.patch("/api/agents/preset-civil-kiosk/settings", json={"tone": "concise"}),
                 403, "preset_read_only")
    assert_error(client.patch("/api/agents/ag_000000000000/settings", json={}), 404, "agent_not_found")


def test_delete_agent(client: TestClient) -> None:
    aid = create_csv_agent(client)["agent_id"]
    r = client.delete(f"/api/agents/{aid}")
    assert r.status_code == 204 and r.content == b""
    assert_error(client.get(f"/api/agents/{aid}"), 404, "agent_not_found")
    assert_error(client.delete(f"/api/agents/{aid}"), 404, "agent_not_found")
    assert_error(client.delete("/api/agents/preset-restaurant"), 403, "preset_read_only")


# ---- chunks / sessions ----


def test_chunks_pagination(client: TestClient) -> None:
    aid = create_csv_agent(client)["agent_id"]
    r = client.get(f"/api/agents/{aid}/chunks", params={"offset": 2, "limit": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 12
    assert [c["chunk_id"] for c in body["items"]] == ["q-003", "q-004", "q-005"]
    assert set(body["items"][0]) == {"chunk_id", "title", "text"}
    assert len(client.get(f"/api/agents/{aid}/chunks").json()["items"]) == 12
    assert client.get(f"/api/agents/{aid}/chunks", params={"limit": 0}).status_code == 422
    assert client.get(f"/api/agents/{aid}/chunks", params={"limit": 201}).status_code == 422
    assert_error(client.get("/api/agents/ag_000000000000/chunks"), 404, "agent_not_found")


def test_open_session(client: TestClient) -> None:
    r = client.post("/api/agents/preset-civil-kiosk/sessions")
    assert r.status_code == 201
    body = r.json()
    assert body["session_id"].startswith("s_")
    assert body["agent_id"] == "preset-civil-kiosk"
    assert body["questions_left"] == 30
    assert re.match(ISO_Z, body["expires_at"])
    assert_error(client.post("/api/agents/ag_000000000000/sessions"), 404, "agent_not_found")


# ---- compare ----


def test_compare_success(client: TestClient) -> None:
    aid = create_csv_agent(client)["agent_id"]
    sid = open_session(client, aid)
    r = client.post(f"/api/agents/{aid}/compare", json={
        "session_id": sid, "question": "주차는 어디에 하나요?",
        "a": {"answer_length": "detailed"}, "b": {"answer_length": "one_sentence"},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["question"] == "주차는 어디에 하나요?"
    assert body["questions_left"] == 29
    assert body["a"]["settings"]["answer_length"] == "detailed"
    assert body["b"]["settings"]["answer_length"] == "one_sentence"
    assert body["a"]["answer_kind"] == "grounded"
    assert body["a"]["sentence_count"] == 2 and body["b"]["sentence_count"] == 1
    assert body["diff"]["sentence_count"] == -1
    assert "B의 답이 1문장 짧습니다." in body["notes"]
    side = body["a"]
    assert set(side["timings"]) == {"listen_ms", "search_ms", "think_ms", "speak_ms", "first_audio_ms", "total_ms"}
    assert side["candidates"][0]["chunk_id"] == "q-001"
    assert set(side["sentences"][0]) == {"index", "text", "supported", "evidence", "audio_wav_b64", "speak_ms"}


def test_compare_errors(client: TestClient) -> None:
    aid = create_csv_agent(client)["agent_id"]
    q = {"question": "주차는 어디에 하나요?", "a": {}, "b": {}}
    assert_error(client.post("/api/agents/ag_000000000000/compare", json={"session_id": "s_x", **q}),
                 404, "agent_not_found")
    assert_error(client.post(f"/api/agents/{aid}/compare", json={"session_id": "s_x", **q}),
                 404, "session_not_found")
    other = open_session(client, "preset-civil-kiosk")
    assert_error(client.post(f"/api/agents/{aid}/compare", json={"session_id": other, **q}),
                 404, "session_not_found")
    sid = open_session(client, aid)
    assert client.post(f"/api/agents/{aid}/compare",
                       json={"session_id": sid, "question": "주차", "a": {"bm25": 1}, "b": {}}).status_code == 422


def test_compare_question_limit() -> None:
    a = make_app(session_max_questions=1)
    try:
        c = TestClient(a)
        aid = create_csv_agent(c)["agent_id"]
        sid = open_session(c, aid)
        q = {"session_id": sid, "question": "주차는 어디에 하나요?", "a": {}, "b": {}}
        assert c.post(f"/api/agents/{aid}/compare", json=q).status_code == 200
        assert_error(c.post(f"/api/agents/{aid}/compare", json=q), 429, "question_limit")
    finally:
        a.state.scorecard_jobs.shutdown()


def test_compare_busy_refunds(app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    rt = rt_of(app)
    rt.gate = TurnGate(1, 8)
    monkeypatch.setattr(compare_mod, "WAIT_TIMEOUT_S", 0.05)
    aid = create_csv_agent(client)["agent_id"]
    sid = open_session(client, aid)
    q = {"session_id": sid, "question": "주차는 어디에 하나요?", "a": {}, "b": {}}
    held = rt.gate.enter()
    try:
        assert_error(client.post(f"/api/agents/{aid}/compare", json=q), 503, "busy")
    finally:
        held.release()
    r = client.post(f"/api/agents/{aid}/compare", json=q)
    assert r.status_code == 200
    assert r.json()["questions_left"] == 29  # 503 때 쓴 질문은 되돌려졌다


# ---- scorecards ----


def poll_done(client: TestClient, job_id: str, timeout_s: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = client.get(f"/api/scorecards/{job_id}")
        assert r.status_code == 200, r.text
        body: dict[str, Any] = r.json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError("scorecard did not finish")


def test_scorecard_submit_and_poll(client: TestClient) -> None:
    aid = create_csv_agent(client)["agent_id"]
    r = client.post(f"/api/agents/{aid}/scorecards", json={"n": 10, "voice": True})
    assert r.status_code == 202, r.text
    acc = r.json()
    assert acc["job_id"].startswith("sc_")
    assert acc["status"] in ("queued", "running", "done")
    assert isinstance(acc["position"], int)
    job = poll_done(client, acc["job_id"])
    assert job["status"] == "done", job
    assert job["agent_id"] == aid
    assert job["error"] is None
    assert job["progress"] == {"done": 10, "total": 10}
    report = job["report"]
    assert report["text"]["total"] == 10
    assert report["voice"] is None and report["voice_unavailable_reason"] == "stub_audio"
    assert report["generated_by"] == "rules"
    assert report["first_audio_basis"] == "text"


def test_scorecard_running_conflict_and_busy() -> None:
    a = make_app(scorecard_queue_max=0)
    rt = rt_of(a)
    rt.gate = TurnGate(1, 8)
    held = rt.gate.enter()
    try:
        c = TestClient(a)
        aid = create_csv_agent(c)["agent_id"]
        first = c.post(f"/api/agents/{aid}/scorecards", json={"n": 10, "voice": False})
        assert first.status_code == 202
        job_id = first.json()["job_id"]
        detail = assert_error(c.post(f"/api/agents/{aid}/scorecards", json={"n": 10}), 409, "scorecard_running")
        assert detail["job_id"] == job_id
        assert_error(c.post("/api/agents/preset-restaurant/scorecards", json={"n": 10}), 503, "busy")
        held.release()
        assert poll_done(c, job_id)["status"] == "done"
    finally:
        held.release()
        a.state.scorecard_jobs.shutdown()


def test_scorecard_errors(client: TestClient) -> None:
    assert_error(client.post("/api/agents/ag_000000000000/scorecards", json={}), 404, "agent_not_found")
    assert client.post("/api/agents/preset-restaurant/scorecards", json={"n": 9}).status_code == 422
    assert client.post("/api/agents/preset-restaurant/scorecards", json={"n": 31}).status_code == 422
    assert_error(client.get("/api/scorecards/sc_000000000000"), 404, "job_not_found")


def test_scorecard_default_body(client: TestClient) -> None:
    aid = create_csv_agent(client)["agent_id"]
    r = client.post(f"/api/agents/{aid}/scorecards")
    assert r.status_code == 202, r.text
    job = poll_done(client, r.json()["job_id"])
    assert job["status"] == "done"
    assert job["report"]["question_count"] <= 30

