import re
from pathlib import Path

import httpx
from playwright.sync_api import Page

PUBLIC_ID = "faq-229"
PUBLIC_QUESTION = "시흥시 인구"
PUBLIC_QUERY = "시흥시 인구 궁금해요"


def _ask(base_url: str, text: str) -> dict:
    r = httpx.post(f"{base_url}/api/ask", json={"text": text}, timeout=60)
    assert r.status_code == 200
    return r.json()


def test_bm25_public_question_hits_public_id(base_url: str) -> None:
    body = _ask(base_url, PUBLIC_QUESTION)
    assert body["source"]["id"] == PUBLIC_ID
    assert "시흥시" in body["source"]["source"]
    assert body["answer"].strip()
    assert "찾지 못했습니다" not in body["answer"]
    assert body["timings"]["retrieve_ms"] < 50


def test_bm25_paraphrase_hits_public_id(base_url: str) -> None:
    body = _ask(base_url, PUBLIC_QUERY)
    assert body["source"]["id"] == PUBLIC_ID


def test_bm25_unrelated_query_falls_back(base_url: str) -> None:
    body = _ask(base_url, "qwerty zxcv")
    assert body["source"] is None
    assert "찾지 못했습니다" in body["answer"]


def test_bm25_demo_page_shows_public_source(page: Page, base_url: str, shot_dir: Path) -> None:
    page.goto(base_url)
    page.fill("#question", PUBLIC_QUERY)
    page.click("#ask")
    page.wait_for_selector('#result[data-state="answered"]', timeout=20000)
    assert page.locator("#source").inner_text().strip() == f"출처: {PUBLIC_ID}"
    assert len(page.locator("#answer").inner_text().strip()) >= 20
    assert len(re.findall(r"ms", page.locator("#timings").inner_text())) == 4
    page.wait_for_function("document.getElementById('audio').duration > 0.5", timeout=10000)
    page.screenshot(path=str(shot_dir / "demo-bm25-answered.png"), full_page=True)
