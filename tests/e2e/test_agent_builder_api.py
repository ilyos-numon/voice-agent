import base64
import json
import time

import httpx
import pytest

TIMEOUT = 60

CSV_HEADER = "질문,답변\n"
CSV_ROWS = [
    ("주차는 어디에 하나요?", "지하 1층 주차장을 이용하세요. 두 시간 무료입니다. 정산은 출구에서 합니다."),
    ("영업시간이 어떻게 되나요?", "매일 오전 10시부터 오후 9시까지 영업합니다."),
    ("반려동물 동반이 가능한가요?", "소형 반려동물은 이동 가방에 넣으면 입장할 수 있습니다."),
    ("와이파이 비밀번호가 무엇인가요?", "계산대에서 안내 카드를 받아 가세요."),
    ("휴무일은 언제인가요?", "매주 월요일은 쉬는 날입니다."),
]
CSV_TEXT = CSV_HEADER + "".join(f"{q},{a}\n" for q, a in CSV_ROWS)


@pytest.fixture()
def api(base_url: str):
    with httpx.Client(base_url=base_url, timeout=TIMEOUT) as c:
        yield c


@pytest.fixture()
def created(api: httpx.Client):
    ids: list[str] = []

    def make(knowledge: dict, settings: dict | None = None, name: str = "테스트 상담원") -> dict:
        body: dict = {"name": name, "knowledge": knowledge}
        if settings:
            body["settings"] = settings
        r = api.post("/api/agents", json=body)
        assert r.status_code == 201, r.text
        ids.append(r.json()["agent_id"])
        return r.json()

    yield make
    for agent_id in ids:
        api.delete(f"/api/agents/{agent_id}")


def open_session(api: httpx.Client, agent_id: str) -> dict:
    r = api.post(f"/api/agents/{agent_id}/sessions")
    assert r.status_code == 201, r.text
    return r.json()


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    events = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        name = ""
        data = ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        events.append((name, json.loads(data)))
    return events


def ask(api: httpx.Client, agent_id: str, session_id: str, text: str) -> dict:
    """Run one text turn and return {meta, sentences, done, events}."""
    r = api.post(f"/api/agents/{agent_id}/turns/stream", json={"session_id": session_id, "text": text})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    names = [n for n, _ in events]
    assert "error" not in names, events
    meta = next(d for n, d in events if n == "meta")
    sentences = [d for n, d in events if n == "sentence"]
    done = next(d for n, d in events if n == "done")
    return {"meta": meta, "sentences": sentences, "done": done, "events": events}


def ask_fresh(api: httpx.Client, agent_id: str, text: str) -> dict:
    return ask(api, agent_id, open_session(api, agent_id)["session_id"], text)


def test_presets(api: httpx.Client) -> None:
    r = api.get("/api/presets")
    assert r.status_code == 200
    items = r.json()["items"]
    assert [p["preset_id"] for p in items] == ["civil-kiosk", "restaurant", "hospital", "office-policy"]
    for p in items:
        assert p["agent_id"] == f"preset-{p['preset_id']}"
        assert p["title"] and p["description"]
        assert len(p["sample_questions"]) == 3
        assert p["chunk_count"] > 0
    civil = items[0]
    assert civil["chunk_count"] >= 5
    got = api.get(f"/api/agents/{civil['agent_id']}")
    assert got.status_code == 200
    assert got.json()["preset_id"] == "civil-kiosk"
    assert got.json()["expires_at"] is None


def test_options_no_engine_terms(api: httpx.Client) -> None:
    r = api.get("/api/options")
    assert r.status_code == 200
    body = r.json()
    assert {v["value"] for v in body["voices"]} == {"calm_female", "bright_female", "calm_male", "deep_male"}
    assert body["limits"]["max_text_chars"] == 20000
    assert body["limits"]["max_questions_per_session"] == 30
    assert isinstance(body["voice_input_available"], bool)
    assert isinstance(body["summary_available"], bool)
    labels = " ".join(
        o["label"] for key in ("answer_length", "tone", "when_unknown", "voices") for o in body[key]
    ).lower()
    for term in ("whisper", "supertonic", "bm25", "llm", "qwen", "stt", "tts", "embedding", "faiss"):
        assert term not in labels
    for p in api.get("/api/presets").json()["items"]:
        text = (p["title"] + p["description"]).lower()
        for term in ("whisper", "supertonic", "bm25", "stt", "tts"):
            assert term not in text


def test_csv_agent_first_turn_under_60s(api: httpx.Client, created) -> None:
    started = time.monotonic()
    agent = created({"kind": "faq_csv", "csv": CSV_TEXT})
    assert agent["chunk_count"] == 5
    assert agent["preset_id"] is None
    assert agent["share_path"].endswith(agent["agent_id"])
    turn = ask_fresh(api, agent["agent_id"], CSV_ROWS[1][0])
    elapsed = time.monotonic() - started
    assert elapsed < 60
    assert turn["meta"]["candidates"][0]["chunk_id"] == "q-002"
    assert turn["meta"]["answer_kind"] == "grounded"
    assert turn["sentences"][0]["supported"] is True
    assert turn["sentences"][0]["evidence"][0]["chunk_id"] == "q-002"


def test_text_agent_chunks(api: httpx.Client, created) -> None:
    paragraphs = [f"{i}번 안내입니다. " + ("이 문장은 안내 자료를 길게 만들기 위한 내용입니다. " * 25) for i in range(1, 6)]
    agent = created({"kind": "text", "text": "\n\n".join(paragraphs)})
    assert agent["chunk_count"] >= 5
    r = api.get(f"/api/agents/{agent['agent_id']}/chunks", params={"limit": 200})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == agent["chunk_count"]
    assert body["items"][0]["chunk_id"] == "c-001"
    assert all(1 <= len(it["text"]) <= 600 for it in body["items"])


def test_receipt_fields(api: httpx.Client, created) -> None:
    agent = created({"kind": "faq_csv", "csv": CSV_TEXT})
    turn = ask_fresh(api, agent["agent_id"], "주차 어디에 하나요?")
    meta, done = turn["meta"], turn["done"]
    names = [n for n, _ in turn["events"]]
    assert names[0] in ("meta", "queue")
    assert names[-1] == "done"
    for key in ("turn_id", "transcript", "answer_kind", "sentence_count", "candidates", "timings"):
        assert key in meta
    assert meta["transcript"] == "주차 어디에 하나요?"
    assert 1 <= len(meta["candidates"]) <= 3
    for key in ("rank", "chunk_id", "title", "score"):
        assert key in meta["candidates"][0]
    for key in ("listen_ms", "search_ms", "think_ms"):
        assert key in meta["timings"]
    assert meta["sentence_count"] == len(turn["sentences"])
    assert [s["index"] for s in turn["sentences"]] == list(range(len(turn["sentences"])))
    for s in turn["sentences"]:
        assert s["text"]
        assert isinstance(s["supported"], bool)
        assert base64.b64decode(s["audio_wav_b64"])[:4] == b"RIFF"
        assert "speak_ms" in s and "elapsed_ms" in s
        for e in s["evidence"]:
            assert {"chunk_id", "title", "quote", "overlap"} <= set(e)
            assert 0 <= e["overlap"] <= 1
    for key in ("first_audio_ms", "total_ms", "queue_ms", "speak_ms"):
        assert key in done["timings"]
    assert done["questions_left"] == 29
    assert done["summary_used"] is False


def test_civil_sentinel(api: httpx.Client) -> None:
    turn = ask_fresh(api, "preset-civil-kiosk", "등본 떼려면 뭐 필요해요?")
    assert turn["meta"]["answer_kind"] == "grounded"
    assert turn["meta"]["candidates"][0]["chunk_id"] == "faq-001"
    assert turn["sentences"][0]["supported"] is True


def test_preset_samples_grounded(api: httpx.Client) -> None:
    for p in api.get("/api/presets").json()["items"]:
        for q in p["sample_questions"]:
            turn = ask_fresh(api, p["agent_id"], q)
            assert turn["meta"]["answer_kind"] == "grounded", (p["preset_id"], q)
            assert turn["meta"]["candidates"], (p["preset_id"], q)


def test_unknown_and_handoff(api: httpx.Client, created) -> None:
    question = "우주 정거장 발사 일정 알려줘"
    plain = created({"kind": "faq_csv", "csv": CSV_TEXT})
    turn = ask_fresh(api, plain["agent_id"], question)
    assert turn["meta"]["answer_kind"] == "unknown"
    assert [s["text"] for s in turn["sentences"]] == ["제가 가진 자료에는 그 내용이 없어 답하기 어렵습니다."]
    assert turn["sentences"][0]["supported"] is False
    assert turn["sentences"][0]["evidence"] == []

    msg = "본점 안내데스크로 문의해 주세요."
    handoff = created(
        {"kind": "faq_csv", "csv": CSV_TEXT}, {"when_unknown": "handoff", "handoff_message": msg}
    )
    turn = ask_fresh(api, handoff["agent_id"], question)
    assert turn["meta"]["answer_kind"] == "unknown"
    assert [s["text"] for s in turn["sentences"]] == [msg]


def test_avoid_topic(api: httpx.Client, created) -> None:
    agent = created({"kind": "faq_csv", "csv": CSV_TEXT}, {"avoid_topics": ["주차"]})
    turn = ask_fresh(api, agent["agent_id"], "주차는 어디에 하나요?")
    assert turn["meta"]["answer_kind"] == "avoided"
    assert turn["meta"]["candidates"] == []
    assert [s["text"] for s in turn["sentences"]] == ["그 주제는 안내해 드리지 않습니다."]
    assert turn["sentences"][0]["supported"] is False
    assert turn["sentences"][0]["evidence"] == []


def test_compare_length(api: httpx.Client, created) -> None:
    agent = created({"kind": "faq_csv", "csv": CSV_TEXT})
    session = open_session(api, agent["agent_id"])
    r = api.post(
        f"/api/agents/{agent['agent_id']}/compare",
        json={
            "session_id": session["session_id"],
            "question": "주차는 어디에 하나요?",
            "a": {"answer_length": "one_sentence"},
            "b": {"answer_length": "detailed"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["a"]["settings"]["answer_length"] == "one_sentence"
    assert body["b"]["settings"]["answer_length"] == "detailed"
    assert body["a"]["sentence_count"] == 1
    assert body["b"]["sentence_count"] > body["a"]["sentence_count"]
    assert body["b"]["char_count"] > body["a"]["char_count"]
    assert body["diff"]["sentence_count"] == body["b"]["sentence_count"] - body["a"]["sentence_count"]
    assert any("B의 답이" in n and "깁니다" in n for n in body["notes"])
    assert body["questions_left"] == 29
    assert api.get(f"/api/agents/{agent['agent_id']}").json()["settings"]["answer_length"] == "short"


def test_caps(api: httpx.Client, created) -> None:
    too_long = api.post("/api/agents", json={"knowledge": {"kind": "text", "text": "가" * 20001}})
    assert too_long.status_code == 413
    assert too_long.json()["detail"]["code"] == "knowledge_too_large"

    agent = created({"kind": "faq_csv", "csv": CSV_TEXT})
    session = open_session(api, agent["agent_id"])
    for i in range(30):
        ask(api, agent["agent_id"], session["session_id"], f"주차 질문 {i}")
    over = api.post(
        f"/api/agents/{agent['agent_id']}/turns/stream",
        json={"session_id": session["session_id"], "text": "한 번 더"},
    )
    assert over.status_code == 429
    assert over.json()["detail"]["code"] == "question_limit"

    missing = api.get("/api/agents/ag_000000000000")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "agent_not_found"
    assert api.post("/api/agents/ag_000000000000/sessions").status_code == 404

    deleted = api.delete("/api/agents/preset-restaurant")
    assert deleted.status_code == 403
    assert deleted.json()["detail"]["code"] == "preset_read_only"
    assert api.get("/api/agents/preset-restaurant").status_code == 200


def test_scorecard_job(api: httpx.Client) -> None:
    r = api.post("/api/agents/preset-restaurant/scorecards", json={"n": 10, "voice": False})
    assert r.status_code in (202, 409), r.text
    job_id = r.json()["job_id"] if r.status_code == 202 else r.json()["detail"]["job_id"]
    deadline = time.monotonic() + 120
    job: dict = {}
    while time.monotonic() < deadline:
        job = api.get(f"/api/scorecards/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(1)
    assert job["status"] == "done", job
    report = job["report"]
    assert 1 <= report["question_count"] <= 10
    assert report["text"]["total"] == report["question_count"]
    assert 0 <= report["text"]["hits"] <= report["text"]["total"]
    assert report["voice"] is None
    assert report["caveat"]
    assert set(report["by_style"]) == {"verbatim", "colloquial"}
    assert report["first_audio_ms"]["p50"] >= 0
    assert api.get("/api/scorecards/sc_000000000000").status_code == 404
