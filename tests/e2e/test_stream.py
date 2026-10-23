import json
import time
from pathlib import Path

import httpx
from playwright.sync_api import Page

from app.pipeline.sentences import split_sentences
from app.pipeline.stubs import FALLBACK_ANSWER

QUESTION = "주민등록등본 떼려면 뭐 필요해요?"
DONE_KEYS = {"stt_ms", "retrieve_ms", "llm_ms", "tts_ms", "first_audio_ms", "total_ms"}


def read_events(base_url: str, text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    name = None
    with httpx.stream(
        "POST", f"{base_url}/api/ask-stream", json={"text": text}, timeout=90
    ) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: ") and name is not None:
                events.append((name, json.loads(line[len("data: "):])))
                name = None
    return events


def test_stream_events_in_order(base_url: str) -> None:
    events = read_events(base_url, QUESTION)
    names = [n for n, _ in events]
    assert names[0] == "meta"
    assert names[-1] == "done"
    audio = [d for n, d in events if n == "audio"]
    assert len(audio) >= 1
    assert names == ["meta"] + ["audio"] * len(audio) + ["done"]
    assert [a["index"] for a in audio] == list(range(len(audio)))
    meta, done = events[0][1], events[-1][1]
    assert meta["sentence_count"] == len(audio) == done["sentence_count"]
    assert set(done["timings"]) == DONE_KEYS


def test_stream_fallback_audio_per_sentence(base_url: str) -> None:
    events = read_events(base_url, "xyzzy")
    assert events[0][0] == "meta"
    assert events[0][1]["source"] is None
    assert [n for n, _ in events].count("audio") == len(
        split_sentences(FALLBACK_ANSWER)
    )
    assert events[-1][0] == "done"


def test_stream_blank_text_422(base_url: str) -> None:
    t = time.perf_counter()
    r = httpx.post(f"{base_url}/api/ask-stream", json={"text": "   "}, timeout=30)
    assert r.status_code == 422
    assert time.perf_counter() - t < 1.0


def test_stream_demo_page_speaks_sentences(page: Page, base_url: str, shot_dir: Path) -> None:
    page.goto(f"{base_url}/static/archive/kiosk/index.html")
    page.fill("#question", QUESTION)
    page.click("#ask")
    page.wait_for_selector('#result[data-state="answered"]', timeout=15000)
    assert page.locator("#sentences li").count() >= 1
    assert "첫 음성" in page.locator("#first-audio").inner_text()
    assert page.locator("#timings").inner_text().count("ms") == 4
    page.screenshot(path=str(shot_dir / "demo-stream-answered.png"), full_page=True)
