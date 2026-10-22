"""Server must run with LLM_BACKEND=qwen. Real API calls: 3 per run."""
import json

import httpx
from playwright.sync_api import Page

from app.pipeline.sentences import split_sentences


def _events(base_url: str, text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    name = None
    with httpx.stream("POST", f"{base_url}/api/ask-stream", json={"text": text}, timeout=90) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: ") and name is not None:
                events.append((name, json.loads(line[len("data: "):])))
                name = None
    return events


def test_stream_source_id_and_audio(base_url: str) -> None:
    events = _events(base_url, "시흥시 인구 궁금해요")
    names = [n for n, _ in events]
    assert names[0] == "meta" and names[-1] == "done"
    meta = events[0][1]
    assert meta["source"]["id"] == "faq-229"
    assert names.count("audio") >= 1


def test_stream_long_item_keeps_source_and_shortens(base_url: str) -> None:
    events = _events(base_url, "위반건축물 행정처분")
    names = [n for n, _ in events]
    meta = events[0][1]
    assert meta["source"]["id"] == "faq-020"
    assert len(meta["answer"]) < 577
    assert 1 <= len(split_sentences(meta["answer"])) <= 3
    assert names.count("audio") == meta["sentence_count"]
    assert 1 <= meta["sentence_count"] <= 4
    assert events[-1][0] == "done"


def test_demo_page_live(page: Page, base_url: str, shot_dir) -> None:
    page.goto(base_url)
    page.fill("#question", "시흥시 인구 궁금해요")
    page.click("#ask")
    page.wait_for_selector('#result[data-state="answered"]', timeout=60000)
    assert page.locator("#sentences li").count() >= 1
    assert "faq-229" in (page.inner_text("#source"))
    page.screenshot(path=str(shot_dir / "live-demo.png"), full_page=True)
