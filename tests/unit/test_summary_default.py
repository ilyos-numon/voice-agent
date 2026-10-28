import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.jobs import ScorecardJobs
from app.agents.presets import load_presets
from app.agents.runtime import build_agent_runtime
from app.api.agents import agents_router
from app.config import Settings, get_settings
from app.pipeline.stubs import PassthroughSTT, SilentTTS

ROOT = Path(__file__).resolve().parents[2]
PRESETS = ROOT / "data" / "presets"
PRESET_IDS = {"civil-kiosk", "hospital", "office-policy", "restaurant"}
CSV = (
    "질문,답변\n"
    "주차는 어디에 하나요?,지하 1층 주차장을 이용하세요. 두 시간 무료입니다.\n"
    "영업시간이 어떻게 되나요?,매일 오전 10시부터 오후 9시까지 영업합니다.\n"
)


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    # get_settings() 가 저장소의 .env 를 읽지 않도록 빈 임시 폴더에서 돌린다.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_SUMMARY_DEFAULT", raising=False)
    monkeypatch.setenv("LLM_BACKEND", "stub")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_SUMMARY_DEFAULT", "1")
    get_settings.cache_clear()


@pytest.fixture
def make_client() -> Iterator[Any]:
    apps: list[FastAPI] = []

    def _make() -> TestClient:
        settings = Settings(_env_file=None, presets_dir=PRESETS)  # type: ignore[call-arg]
        a = FastAPI()
        a.include_router(agents_router)
        rt = build_agent_runtime(settings, PassthroughSTT(), SilentTTS())
        a.state.agents = rt
        a.state.scorecard_jobs = ScorecardJobs(rt, max_waiting=settings.scorecard_queue_max)
        apps.append(a)
        return TestClient(a)

    yield _make
    for a in apps:
        a.state.scorecard_jobs.shutdown()


def _preset_summaries(client: TestClient) -> dict[str, bool]:
    items = client.get("/api/presets").json()["items"]
    out: dict[str, bool] = {}
    for it in items:
        r = client.get(f"/api/agents/{it['agent_id']}")
        assert r.status_code == 200, r.text
        out[it["preset_id"]] = r.json()["settings"]["summary"]
    return out


def _create(client: TestClient, **settings: Any) -> dict[str, Any]:
    r = client.post("/api/agents", json={"knowledge": {"kind": "faq_csv", "csv": CSV}, "settings": settings})
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


def test_flag_off_keeps_current_behaviour(make_client: Any) -> None:
    assert get_settings().agent_summary_default is False
    client = make_client()
    assert _preset_summaries(client) == dict.fromkeys(PRESET_IDS, False)
    assert client.get("/api/options").json()["defaults"]["summary"] is False
    assert _create(client)["settings"]["summary"] is False


def test_flag_on_enables_presets_and_new_agents(monkeypatch: pytest.MonkeyPatch, make_client: Any) -> None:
    _flag_on(monkeypatch)
    client = make_client()
    assert _preset_summaries(client) == dict.fromkeys(PRESET_IDS, True)
    assert client.get("/api/options").json()["defaults"]["summary"] is True
    assert _create(client)["settings"]["summary"] is True
    assert _create(client, summary=False)["settings"]["summary"] is False


def test_explicit_preset_summary_wins(tmp_path: Path) -> None:
    presets = tmp_path / "presets"
    shutil.copytree(PRESETS / "restaurant", presets / "restaurant")
    path = presets / "restaurant" / "preset.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["settings"]["summary"] = False
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    [loaded] = load_presets(presets, summary_default=True)
    assert loaded.agent.settings.summary is False
    assert loaded.agent.settings.tone == "friendly"


def test_load_presets_default_is_false() -> None:
    assert all(not p.agent.settings.summary for p in load_presets(PRESETS))
    assert all(p.agent.settings.summary for p in load_presets(PRESETS, summary_default=True))


def test_flag_on_without_key_uses_rule_sentences(monkeypatch: pytest.MonkeyPatch, make_client: Any) -> None:
    _flag_on(monkeypatch)
    client = make_client()
    preset = next(it for it in client.get("/api/presets").json()["items"] if it["preset_id"] == "restaurant")
    aid = preset["agent_id"]
    r = client.post(f"/api/agents/{aid}/sessions")
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]
    r = client.post(f"/api/agents/{aid}/turns/stream", json={"session_id": sid, "text": preset["sample_questions"][0]})
    assert r.status_code == 200, r.text
    events = []
    for block in r.text.split("\n\n"):
        if block.strip():
            ev_line, data_line = block.split("\n")
            events.append((ev_line[7:], json.loads(data_line[6:])))
    done = [d for e, d in events if e == "done"]
    assert len(done) == 1
    assert done[0]["summary_used"] is False
