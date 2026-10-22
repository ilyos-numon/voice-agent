import base64
import re
import time
from pathlib import Path

import httpx
from playwright.sync_api import Page

from app.pipeline.wav import wav_stats

QUESTION = "주민등록등본 떼려면 뭐 필요해요?"


def test_tts_ask_returns_voiced_wav(base_url: str) -> None:
    r = httpx.post(f"{base_url}/api/ask", json={"text": QUESTION}, timeout=30)
    assert r.status_code == 200
    body = r.json()
    s = wav_stats(base64.b64decode(body["audio_wav_b64"]))
    assert s.sample_rate == 44100
    assert s.channels == 1
    assert s.duration_s >= 0.5
    assert s.rms > 200
    assert body["timings"]["tts_ms"] >= 20


def test_tts_fallback_answer_is_voiced(base_url: str) -> None:
    r = httpx.post(f"{base_url}/api/ask", json={"text": "xyzzy"}, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body["source"] is None
    s = wav_stats(base64.b64decode(body["audio_wav_b64"]))
    assert s.duration_s >= 0.5
    assert s.rms > 200


def test_tts_blank_text_422_fast(base_url: str) -> None:
    t = time.perf_counter()
    r = httpx.post(f"{base_url}/api/ask", json={"text": "   "}, timeout=30)
    elapsed = time.perf_counter() - t
    assert r.status_code == 422
    assert elapsed < 1.0


def test_tts_demo_page_audio_has_duration(page: Page, base_url: str, shot_dir: Path) -> None:
    page.goto(base_url)
    page.fill("#question", QUESTION)
    page.click("#ask")
    page.wait_for_selector('#result[data-state="answered"]', timeout=15000)
    page.wait_for_function("document.getElementById('audio').duration > 0.5", timeout=10000)
    m = re.search(r"말하기 (\d+(\.\d+)?)ms", page.locator("#timings").inner_text())
    assert m is not None
    assert float(m.group(1)) > 0
    page.screenshot(path=str(shot_dir / "demo-tts-answered.png"), full_page=True)
