import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("ILLY_BASE_URL", "http://localhost:8765")
FIXTURE_WAV = Path(__file__).resolve().parents[1] / "fixtures" / "ask_faq001_ko.wav"
FAKE_MIC_ARGS = [
    "--use-fake-device-for-media-stream",
    "--use-fake-ui-for-media-stream",
    f"--use-file-for-fake-audio-capture={FIXTURE_WAV}",
]
SHOT_DIR = Path(os.environ.get("ILLY_SHOT_DIR", "tests/e2e/screenshots"))


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def shot_dir() -> Path:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    return SHOT_DIR


@pytest.fixture(scope="session")
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=FAKE_MIC_ARGS)
        pg = browser.new_page(viewport={"width": 1024, "height": 768}, permissions=["microphone"])
        yield pg
        pg.close()
        browser.close()
