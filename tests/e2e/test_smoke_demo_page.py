from pathlib import Path

from playwright.sync_api import Page, expect


def test_demo_page_answers_question(page: Page, base_url: str, shot_dir: Path) -> None:
    page.goto(base_url)
    page.screenshot(path=str(shot_dir / "demo-idle.png"), full_page=True)

    page.fill("#question", "주민등록등본 떼려면 뭐 필요해요?")
    page.click("#ask")
    page.wait_for_selector('#result[data-state="answered"]', timeout=5000)

    expect(page.locator("#answer")).to_contain_text("신분증")
    assert page.locator("#source").inner_text().strip() == "출처: faq-001"
    assert page.locator("#timings").inner_text().count("ms") == 4
    page.screenshot(path=str(shot_dir / "demo-answered.png"), full_page=True)


def test_demo_page_empty_question_shows_error(
    page: Page, base_url: str, shot_dir: Path
) -> None:
    page.goto(base_url)
    page.fill("#question", "")
    page.click("#ask")
    page.wait_for_selector('#result[data-state="error"]', timeout=5000)

    expect(page.locator("#error")).to_be_visible()
    page.screenshot(path=str(shot_dir / "demo-error.png"), full_page=True)
