import base64
import re
from pathlib import Path

import httpx
from playwright.sync_api import Page

from app.pipeline.wav import pcm16_to_wav, wav_stats

FIXTURE_WAV = Path(__file__).resolve().parents[1] / "fixtures" / "ask_faq001_ko.wav"
URL = "/api/ask-audio"


def test_stt_upload_wav_recognizes_faq001(base_url: str) -> None:
    r = httpx.post(
        f"{base_url}{URL}", content=FIXTURE_WAV.read_bytes(), headers={"content-type": "audio/wav"}, timeout=60
    )
    assert r.status_code == 200
    body = r.json()
    assert "등본" in body["transcript"]
    assert body["source"]["id"] == "faq-001"
    assert body["timings"]["stt_ms"] > 0
    s = wav_stats(base64.b64decode(body["audio_wav_b64"]))
    assert s.duration_s >= 0.5
    assert s.rms > 200


def test_stt_upload_empty_body_400(base_url: str) -> None:
    r = httpx.post(f"{base_url}{URL}", content=b"", headers={"content-type": "audio/wav"}, timeout=60)
    assert r.status_code == 400
    assert r.json()["detail"] == "empty audio"


def test_stt_upload_garbage_415(base_url: str) -> None:
    r = httpx.post(
        f"{base_url}{URL}", content=b"not audio at all " * 64, headers={"content-type": "audio/wav"}, timeout=60
    )
    assert r.status_code == 415
    assert r.json()["detail"] == "unsupported audio format"


def test_stt_upload_corrupt_webm_400(base_url: str) -> None:
    r = httpx.post(
        f"{base_url}{URL}",
        content=b"\x1a\x45\xdf\xa3" + bytes(range(256)) * 8,
        headers={"content-type": "audio/webm"},
        timeout=60,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "audio decode failed"


def test_stt_upload_silence_422(base_url: str) -> None:
    wav = pcm16_to_wav(b"\x00\x00" * 16000, 16000)
    r = httpx.post(f"{base_url}{URL}", content=wav, headers={"content-type": "audio/wav"}, timeout=60)
    assert r.status_code == 422
    assert r.json()["detail"] == "no speech recognized"


def test_stt_demo_page_mic_to_answer(page: Page, base_url: str, shot_dir: Path) -> None:
    page.goto(f"{base_url}/static/index.html")
    page.click("#mic")
    page.wait_for_selector('#result[data-state="recording"]', timeout=5000)
    page.screenshot(path=str(shot_dir / "demo-stt-recording.png"), full_page=True)
    page.wait_for_timeout(6000)
    page.click("#mic")
    page.wait_for_selector('#result[data-state="answered"]', timeout=30000)
    assert "등본" in page.locator("#transcript").inner_text()
    assert page.locator("#source").inner_text() == "출처: faq-001"
    m = re.search(r"듣기 (\d+(\.\d+)?)ms", page.locator("#timings").inner_text())
    assert m is not None
    assert float(m.group(1)) > 0
    page.wait_for_function("document.getElementById('audio').duration > 0.5", timeout=10000)
    page.screenshot(path=str(shot_dir / "demo-stt-answered.png"), full_page=True)
