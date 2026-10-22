import base64
import json
import time
from pathlib import Path

import httpx
from playwright.sync_api import Page

from app.pipeline.wav import wav_stats

LONG_ID = "faq-020"
LONG_QUESTION = "위반건축물 행정처분"


def stream_events(base_url: str, text: str) -> tuple[list[tuple[str, dict]], float | None]:
    """Return (events, wall-clock ms until first audio event line arrived)."""
    events: list[tuple[str, dict]] = []
    first_audio_ms: float | None = None
    name = None
    t0 = time.perf_counter()
    with httpx.stream(
        "POST", f"{base_url}/api/ask-stream", json={"text": text}, timeout=90
    ) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("event: "):
                name = line[len("event: "):]
                if name == "audio" and first_audio_ms is None:
                    first_audio_ms = (time.perf_counter() - t0) * 1000
            elif line.startswith("data: ") and name is not None:
                events.append((name, json.loads(line[len("data: "):])))
                name = None
    return events, first_audio_ms


def test_stream_first_audio_faster_than_full_tts(base_url: str) -> None:
    r = httpx.post(f"{base_url}/api/ask", json={"text": LONG_QUESTION}, timeout=90)
    assert r.status_code == 200
    assert r.json()["source"]["id"] == LONG_ID
    a = r.json()["timings"]["tts_ms"]
    events, b = stream_events(base_url, LONG_QUESTION)
    audio = [d for n, d in events if n == "audio"]
    done = events[-1][1]
    print(f"A={a:.1f} B'={b:.1f} ratio={b / a:.3f}")
    assert b is not None and b < 0.6 * a
    assert len(audio) >= 4
    assert done["timings"]["first_audio_ms"] < 3000


def test_stream_each_chunk_voiced(base_url: str) -> None:
    events, _ = stream_events(base_url, LONG_QUESTION)
    audio = [d for n, d in events if n == "audio"]
    assert len(audio) >= 1
    for a in audio:
        s = wav_stats(base64.b64decode(a["audio_wav_b64"]))
        assert s.sample_rate == 44100
        assert s.rms > 200


def test_stream_demo_page_shows_playing_sentence(
    page: Page, base_url: str, shot_dir: Path
) -> None:
    page.goto(base_url)
    page.fill("#question", LONG_QUESTION)
    page.click("#ask")
    page.wait_for_selector('#result[data-state="speaking"]', timeout=20000)
    page.wait_for_selector("#sentences li.playing", timeout=20000)
    page.screenshot(path=str(shot_dir / "demo-stream-speaking.png"), full_page=True)
    page.wait_for_selector('#result[data-state="answered"]', timeout=60000)
