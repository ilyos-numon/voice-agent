import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("ILLY_BASE_URL", "http://localhost:8765")
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
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1024, "height": 768})
        yield pg
        pg.close()
        browser.close()
