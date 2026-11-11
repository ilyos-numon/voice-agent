from pathlib import Path

from playwright.sync_api import BrowserContext, Page, expect


def test_studio_voice_real(page: Page, base_url: str, shot_dir: Path) -> None:
    ctx: BrowserContext = page.context.browser.new_context(
        viewport={"width": 1024, "height": 768}, permissions=["microphone"]
    )
    try:
        pg = ctx.new_page()
        pg.goto(f"{base_url}/studio/app?agent=preset-civil-kiosk")
        pg.wait_for_selector("body[data-ready=true]", timeout=30000)
        expect(pg.locator("#mic-btn")).to_be_visible()
        pg.click("#mic-btn")
        expect(pg.locator("#mic-btn")).to_have_attribute("aria-pressed", "true")
        pg.wait_for_timeout(5000)  # 가짜 마이크가 WAV(약 4초)를 재생하는 동안 녹음
        pg.click("#mic-btn")
        turn = pg.locator('.ws-turn[data-state="answered"]').first
        expect(turn).to_be_visible(timeout=60000)
        expect(turn.locator(".ws-question")).to_contain_text("등본")
        assert turn.locator(".ws-sentence").count() >= 1
        pg.screenshot(path=str(shot_dir / "ws-voice.png"), full_page=True)
    finally:
        ctx.close()
