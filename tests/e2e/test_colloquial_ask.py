import json
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page

from app.pipeline.bm25 import BM25Retriever, load_faq_any

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "faq_eval_colloquial.jsonl"
FAQ = ROOT / "data" / "faq" / "faq.jsonl"


def _rows() -> list[dict]:
    return [json.loads(ln) for ln in FIXTURE.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _ask(base_url: str, text: str) -> dict:
    r = httpx.post(f"{base_url}/api/ask", json={"text": text}, timeout=60)
    assert r.status_code == 200, (text, r.status_code)
    return r.json()


@pytest.fixture(scope="module")
def retriever() -> BM25Retriever:
    return BM25Retriever(load_faq_any(FAQ))


@pytest.fixture(scope="module")
def cases(base_url: str, retriever: BM25Retriever) -> list[dict]:
    out = []
    for row in _rows():
        hits = retriever.search(row["query"], 3)
        out.append(
            {
                "row": row,
                "offline": hits[0].id if hits else None,
                "body": _ask(base_url, row["query"]),
            }
        )
    return out


def test_fixture_has_46_rows() -> None:
    assert len(_rows()) == 46


def test_server_matches_offline_bm25_top1(cases: list[dict]) -> None:
    for c in cases:
        body = c["body"]
        server_id = body["source"]["id"] if body["source"] else None
        assert server_id == c["offline"], (c["row"]["qid"], server_id, c["offline"])
        assert body["timings"]["retrieve_ms"] < 50, c["row"]["qid"]


def test_server_returns_expected_id_where_offline_correct(cases: list[dict]) -> None:
    hit = [c for c in cases if c["offline"] is not None and c["offline"] == c["row"]["expected_id"]]
    print(f"offline-correct rows: {len(hit)}")
    for c in hit:
        assert c["body"]["source"]["id"] == c["row"]["expected_id"], c["row"]["qid"]
        assert c["body"]["answer"].strip(), c["row"]["qid"]


def test_no_result_rows_fall_back(base_url: str, cases: list[dict]) -> None:
    empty = [c for c in cases if c["offline"] is None]
    print(f"offline-empty rows: {len(empty)}")
    if empty:
        for c in empty:
            assert c["body"]["source"] is None, c["row"]["qid"]
            assert "찾지 못했습니다" in c["body"]["answer"], c["row"]["qid"]
    else:
        body = _ask(base_url, "qwerty zxcv")
        assert body["source"] is None
        assert "찾지 못했습니다" in body["answer"]


def test_whitespace_text_rejected(base_url: str) -> None:
    r = httpx.post(f"{base_url}/api/ask", json={"text": "   "}, timeout=30)
    assert r.status_code == 422


def test_demo_page_shows_colloquial_source(
    page: Page, base_url: str, shot_dir: Path, cases: list[dict]
) -> None:
    colloquial = [c for c in cases if c["row"]["kind"] == "colloquial"]
    assert colloquial, "no colloquial rows in fixture"
    correct = [c for c in colloquial if c["offline"] == c["row"]["expected_id"]]
    target = correct[0] if correct else colloquial[0]
    expected = target["row"]["expected_id"] if correct else target["offline"]
    page.goto(base_url)
    page.fill("#question", target["row"]["query"])
    page.click("#ask")
    page.wait_for_selector('#result[data-state="answered"]', timeout=20000)
    source_text = page.locator("#source").inner_text().strip()
    if expected is None:
        assert "출처" not in source_text or source_text == ""
    else:
        assert source_text == f"출처: {expected}"
    page.screenshot(path=str(shot_dir / "colloquial-answered.png"), full_page=True)
