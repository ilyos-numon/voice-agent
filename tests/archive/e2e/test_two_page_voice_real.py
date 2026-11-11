from pathlib import Path

from playwright.sync_api import Page, expect


def test_talk_mic_voice_question(page: Page, base_url: str, shot_dir: Path) -> None:
    page.goto(f"{base_url}/talk?agent=preset-civil-kiosk")
    page.wait_for_selector("body[data-ready=true]", timeout=30000)
    expect(page.locator("#mic-btn")).to_be_visible()
    page.click("#mic-btn")
    expect(page.locator("#mic-btn")).to_have_attribute("aria-pressed", "true")
    page.wait_for_timeout(5000)
    page.click("#mic-btn")
    turn = page.locator('.turn[data-state="answered"]').first
    expect(turn).to_be_visible(timeout=60000)
    expect(turn.locator(".turn-question")).to_contain_text("등본")
    assert turn.locator(".sentence").count() >= 1
    expect(turn.locator(".receipt-timings")).to_contain_text("듣기")
    page.screenshot(path=str(shot_dir / "two-page-voice.png"), full_page=True)
