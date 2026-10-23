from pathlib import Path

from playwright.sync_api import Page, expect

CSV_TEXT = (
    "질문,답변\n"
    "주차는 어디에 하나요?,지하 1층 주차장을 이용하세요. 두 시간 무료입니다. 정산은 출구에서 합니다.\n"
    "영업시간이 어떻게 되나요?,매일 오전 10시부터 오후 9시까지 영업합니다.\n"
    "반려동물 동반이 가능한가요?,소형 반려동물은 이동 가방에 넣으면 입장할 수 있습니다.\n"
    "와이파이 비밀번호가 무엇인가요?,계산대에서 안내 카드를 받아 가세요.\n"
    "휴무일은 언제인가요?,매주 월요일은 쉬는 날입니다.\n"
)


def open_builder(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/static/builder.html")
    page.wait_for_selector("body[data-ready=true]", timeout=30000)


def test_builder_presets_cards(page: Page, base_url: str, shot_dir: Path) -> None:
    open_builder(page, base_url)
    expect(page.locator(".preset-card")).to_have_count(4)
    for title in ("민원 키오스크", "식당 주문 안내", "병원 접수 안내", "사내 규정 Q&A"):
        expect(page.locator("#preset-list")).to_contain_text(title)
    page.screenshot(path=str(shot_dir / "builder-presets.png"), full_page=True)


def test_builder_civil_receipt(page: Page, base_url: str, shot_dir: Path) -> None:
    open_builder(page, base_url)
    page.click('.preset-card[data-preset-id="civil-kiosk"]')
    expect(page.locator("#agent-id")).to_have_text("preset-civil-kiosk")
    page.wait_for_function("document.getElementById('questions-left').textContent.trim() !== '-'")
    page.fill("#ask-input", "등본 떼려면 뭐 필요해요?")
    page.click("#ask-btn")
    first_turn = page.locator("#chat-log .turn").first
    expect(first_turn.locator(".receipt-timings")).to_contain_text("첫 음성까지", timeout=30000)
    expect(first_turn.locator(".receipt-timings")).to_be_visible()
    expect(first_turn.locator(".receipt-candidates")).to_be_visible()
    expect(first_turn.locator(".receipt-candidates")).to_contain_text("점수")
    expect(first_turn.locator(".evidence li").first).to_be_visible()
    expect(first_turn.locator(".sentence").first).to_be_visible()
    expect(page.locator("#questions-left")).to_have_text("29")
    page.screenshot(path=str(shot_dir / "builder-receipt.png"), full_page=True)


def test_builder_create_csv_agent(page: Page, base_url: str, shot_dir: Path) -> None:
    open_builder(page, base_url)
    page.select_option("#kn-kind", "faq_csv")
    page.fill("#kn-input", CSV_TEXT)
    page.click("#create-btn")
    page.wait_for_function(
        "/^ag_[0-9a-f]{12}$/.test(document.getElementById('agent-id').textContent.trim())", timeout=30000
    )
    expect(page.locator("#share-link")).to_contain_text("builder.html?agent=ag_")
    page.fill("#ask-input", "영업시간이 어떻게 되나요?")
    page.click("#ask-btn")
    first_turn = page.locator("#chat-log .turn").first
    expect(first_turn.locator(".sentence").first).to_contain_text("오전 10시", timeout=30000)
    page.screenshot(path=str(shot_dir / "builder-created.png"), full_page=True)


def test_builder_scorecard(page: Page, base_url: str, shot_dir: Path) -> None:
    open_builder(page, base_url)
    page.click('.preset-card[data-preset-id="restaurant"]')
    expect(page.locator("#agent-id")).to_have_text("preset-restaurant")
    page.fill("#sc-n", "10")
    page.click("#scorecard-btn")
    expect(page.locator("#scorecard-report")).to_be_visible(timeout=120000)
    expect(page.locator("#sc-text-hits")).not_to_have_text("-")
    expect(page.locator("#sc-text-hits")).to_contain_text("/")
    expect(page.locator("#sc-caveat")).not_to_be_empty()
    page.screenshot(path=str(shot_dir / "builder-scorecard.png"), full_page=True)


def test_builder_ab_compare(page: Page, base_url: str, shot_dir: Path) -> None:
    open_builder(page, base_url)
    page.click('.preset-card[data-preset-id="restaurant"]')
    expect(page.locator("#agent-id")).to_have_text("preset-restaurant")
    page.wait_for_function("document.getElementById('questions-left').textContent.trim() !== '-'")
    page.fill("#ask-input", "영업시간이 어떻게 돼요?")
    page.select_option("#ab-a-length", "one_sentence")
    page.select_option("#ab-b-length", "detailed")
    page.click("#ab-btn")
    page.wait_for_function(
        "document.querySelectorAll('.ab-side .ab-sentences .sentence').length >= 2", timeout=60000
    )
    expect(page.locator(".ab-side")).to_have_count(2)
    for side in ("a", "b"):
        expect(page.locator(f'.ab-side[data-side="{side}"] .ab-first-audio')).to_contain_text("첫 음성까지")
    expect(page.locator("#ab-notes li").first).to_be_visible()
    page.screenshot(path=str(shot_dir / "builder-ab.png"), full_page=True)
