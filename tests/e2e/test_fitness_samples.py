import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "samples"
UNKNOWN = "제가 가진 자료에는 그 내용이 없어 답하기 어렵습니다."
TIMEOUT = 60

# (id, question, text title, text must-contain, csv title, csv must-contain, scope of contains)
CASES = [
    ("F1", "일요일에도 문 열어요?", "운영 시간", "일요일", "운영 시간이 어떻게 되나요?", "일요일", "first"),
    ("F2", "PT 당일 취소하면 어떻게 돼요?", "개인 트레이닝", "당일 취소하면 1회가 차감됩니다",
     "PT 예약을 바꿀 수 있나요?", "1회가 차감됩니다", "first"),
    ("F3", "수영장 있어요?", None, None, None, None, "unknown"),
    ("F4", "회원권 가격이 얼마예요?", "회원권과 요금", "7만 원", "회원권 가격이 얼마예요?", "7만 원", "all"),
    ("F5", "주차 되나요?", "주차", "2시간까지 무료", "주차 되나요?", "2시간까지 무료", "all"),
    ("F6", "샤워실에 샴푸 있어요?", "샤워실", "샴푸", "샤워실에 샴푸 있어요?", "샴푸", "all"),
]  # fmt: skip


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


def ask_fresh(client: httpx.Client, agent_id: str, text: str) -> dict:
    s = client.post(f"/api/agents/{agent_id}/sessions")
    assert s.status_code == 201, s.text
    r = client.post(
        f"/api/agents/{agent_id}/turns/stream",
        json={"session_id": s.json()["session_id"], "text": text},
    )
    assert r.status_code == 200, r.text
    events = parse_sse(r.text)
    assert "error" not in [n for n, _ in events], events
    return {
        "meta": next(d for n, d in events if n == "meta"),
        "sentences": [d for n, d in events if n == "sentence"],
    }


@pytest.fixture(scope="module")
def client(base_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=base_url, timeout=TIMEOUT) as c:
        yield c


@pytest.fixture(scope="module")
def agents(client: httpx.Client) -> Iterator[dict]:
    txt = (SAMPLES / "fitness-center.txt").read_text(encoding="utf-8")
    csv = (SAMPLES / "fitness-center.csv").read_text(encoding="utf-8")
    created: dict[str, dict] = {}
    for kind, knowledge in (
        ("text", {"kind": "text", "text": txt}),
        ("csv", {"kind": "faq_csv", "csv": csv}),
    ):
        r = client.post("/api/agents", json={"name": f"피트니스 {kind}", "knowledge": knowledge})
        assert r.status_code == 201, r.text
        created[kind] = r.json()
    yield created
    for a in created.values():
        client.delete(f"/api/agents/{a['agent_id']}")


def test_chunk_counts(agents: dict) -> None:
    assert agents["text"]["chunk_count"] == 14
    assert agents["csv"]["chunk_count"] == 18
    assert agents["csv"]["warnings"] == []


@pytest.mark.parametrize("kind", ["text", "csv"])
@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_fitness_question(client: httpx.Client, agents: dict, kind: str, case: tuple) -> None:
    _, question, t_title, t_has, c_title, c_has, scope = case
    turn = ask_fresh(client, agents[kind]["agent_id"], question)
    meta, sentences = turn["meta"], turn["sentences"]
    if scope == "unknown":
        assert meta["answer_kind"] == "unknown"
        assert [s["text"] for s in sentences] == [UNKNOWN]
        assert not sentences[0]["text"].startswith("네,")
        return
    title, needle = (t_title, t_has) if kind == "text" else (c_title, c_has)
    assert meta["answer_kind"] == "grounded", meta
    assert meta["candidates"][0]["title"] == title, meta["candidates"]
    assert sentences[0]["supported"] is True
    haystack = sentences[0]["text"] if scope == "first" else " ".join(s["text"] for s in sentences)
    assert needle in haystack, sentences
