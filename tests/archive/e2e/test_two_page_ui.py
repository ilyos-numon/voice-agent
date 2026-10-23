import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, Page, expect

CSV_TEXT = (
    "질문,답변\n"
    "주차는 어디에 하나요?,지하 1층 주차장을 이용하세요. 두 시간 무료입니다. 정산은 출구에서 합니다.\n"
    "영업시간이 어떻게 되나요?,매일 오전 10시부터 오후 9시까지 영업합니다.\n"
    "반려동물 동반이 가능한가요?,소형 반려동물은 이동 가방에 넣으면 입장할 수 있습니다.\n"
    "와이파이 비밀번호가 무엇인가요?,계산대에서 안내 카드를 받아 가세요.\n"
    "휴무일은 언제인가요?,매주 월요일은 쉬는 날입니다.\n"
)
ENGINE_TERMS = ("BM25", "STT", "TTS", "LLM", "top-k", "chunk")


@pytest.fixture()
def ctx(page: Page) -> Iterator[BrowserContext]:
    c = page.context.browser.new_context(viewport={"width": 1024, "height": 768}, permissions=["microphone"])
    yield c
    c.close()


def open_home(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/")
    page.wait_for_selector("body[data-ready=true]", timeout=30000)


def open_talk(page: Page, base_url: str, agent: str) -> None:
    page.goto(f"{base_url}/talk?agent={agent}")
    page.wait_for_selector("body[data-ready=true]", timeout=30000)
    page.wait_for_function("document.getElementById('questions-left').textContent.trim() !== '-'")


def ask(page: Page, question: str) -> None:
    page.fill("#ask-input", question)
    page.click("#ask-btn")
    expect(page.locator('.turn[data-state="answered"]').first).to_be_visible(timeout=30000)


def create_csv_agent(page: Page, base_url: str, name: str) -> str:
    open_home(page, base_url)
    page.select_option("#kn-kind", "faq_csv")
    page.set_input_files("#kn-file", files=[{"name": "faq.csv", "mimeType": "text/csv", "buffer": CSV_TEXT.encode()}])
    page.fill("#agent-name", name)
    page.click("#create-btn")
    page.wait_for_url(re.compile(r"/talk\?agent=ag_[0-9a-f]{12}"), timeout=30000)
    page.wait_for_selector("body[data-ready=true]", timeout=30000)
    return page.url


def test_home_presets_and_form(page: Page, base_url: str, shot_dir: Path) -> None:
    open_home(page, base_url)
    expect(page.locator(".preset-card")).to_have_count(4)
    for title in ("민원 키오스크", "식당 주문 안내", "병원 접수 안내", "사내 규정 Q&A"):
        expect(page.locator("#preset-list")).to_contain_text(title)
    expect(page.locator("#create-form")).to_be_visible()
    page.screenshot(path=str(shot_dir / "two-page-home.png"), full_page=True)


def test_preset_to_talk_receipt(page: Page, base_url: str, shot_dir: Path) -> None:
    open_home(page, base_url)
    page.click('.preset-card[data-preset-id="civil-kiosk"]')
    page.wait_for_url(re.compile(r"/talk\?agent=preset-civil-kiosk"))
    page.wait_for_selector("body[data-ready=true]", timeout=30000)
    expect(page.locator("#agent-title")).to_have_text("민원 키오스크")
    page.wait_for_function("document.getElementById('questions-left').textContent.trim() !== '-'")
    ask(page, "등본 떼려면 뭐 필요해요?")
    turn = page.locator(".turn").first
    expect(turn.locator("details.receipt")).to_have_attribute("open", "")
    expect(turn.locator(".receipt-timings")).to_contain_text("첫 음성까지")
    assert turn.locator(".receipt-footnotes li").count() >= 1
    expect(turn.locator(".receipt-candidates")).to_contain_text("점수")
    page.wait_for_function(
        "['playing','played'].includes(document.querySelector('.turn .sentence').dataset.audio)", timeout=20000
    )
    expect(page.locator("#questions-left")).to_have_text("29")
    page.screenshot(path=str(shot_dir / "two-page-receipt.png"), full_page=True)


def test_receipt_collapses(page: Page, base_url: str) -> None:
    open_talk(page, base_url, "preset-civil-kiosk")
    ask(page, "등본 떼려면 뭐 필요해요?")
    turn = page.locator(".turn").first
    expect(turn.locator(".receipt-timings")).to_be_visible()
    turn.locator("details.receipt > summary").click()
    expect(turn.locator(".receipt-timings")).to_be_hidden()
    expect(turn.locator(".sentence").first).to_be_visible()


def test_csv_create_to_talk(page: Page, base_url: str, shot_dir: Path) -> None:
    create_csv_agent(page, base_url, "우리 가게 상담원")
    expect(page.locator("#agent-title")).to_have_text("우리 가게 상담원")
    expect(page.locator("#sample-chips button.chip")).to_have_count(3)
    ask(page, "영업시간이 어떻게 되나요?")
    expect(page.locator(".turn .sentence").first).to_contain_text("오전 10시")
    page.screenshot(path=str(shot_dir / "two-page-created.png"), full_page=True)


def test_share_link_direct_entry(page: Page, ctx: BrowserContext, base_url: str, shot_dir: Path) -> None:
    create_csv_agent(page, base_url, "우리 가게 상담원")
    page.click("#share-btn")
    expect(page.locator("#share-status")).not_to_be_empty()
    shared = page.locator("#share-url")
    link = shared.input_value() if shared.is_visible() else ""
    if not link:
        link = page.url
    assert "/talk?agent=ag_" in link
    other = ctx.new_page()
    other.goto(link if link.startswith("http") else f"{base_url}{link}")
    other.wait_for_selector("body[data-ready=true]", timeout=30000)
    expect(other.locator("#agent-title")).to_have_text("우리 가게 상담원")
    expect(other.locator("#questions-left")).to_have_text("30")
    other.screenshot(path=str(shot_dir / "two-page-share.png"), full_page=True)


def test_scorecard_tab(page: Page, base_url: str, shot_dir: Path) -> None:
    open_talk(page, base_url, "preset-restaurant")
    page.select_option("#sc-n", "10")
    page.click("#sc-start")
    expect(page.locator("#sc-report")).to_be_visible(timeout=180000)
    assert " / " in page.locator("#sc-text-hits").inner_text()
    expect(page.locator("#sc-caveat")).not_to_be_empty()
    page.screenshot(path=str(shot_dir / "two-page-scorecard.png"), full_page=True)


def test_ab_tab(page: Page, base_url: str, shot_dir: Path) -> None:
    open_talk(page, base_url, "preset-restaurant")
    before = int(page.locator("#questions-left").inner_text())
    page.click("#tab-ab")
    page.fill("#ab-question", "영업시간이 어떻게 돼요?")
    page.select_option("#ab-a-length", "one_sentence")
    page.select_option("#ab-b-length", "detailed")
    page.click("#ab-start")
    expect(page.locator("#ab-result")).to_be_visible(timeout=60000)
    assert page.locator('.ab-side[data-side="a"] .sentence').count() >= 1
    assert page.locator('.ab-side[data-side="b"] .sentence').count() >= 1
    assert page.locator("#ab-notes li").count() >= 1
    assert int(page.locator("#questions-left").inner_text()) < before
    page.screenshot(path=str(shot_dir / "two-page-ab.png"), full_page=True)


def test_expired_agent(page: Page, base_url: str, shot_dir: Path) -> None:
    page.goto(f"{base_url}/talk?agent=ag_000000000000")
    expect(page.locator("#fatal")).to_be_visible(timeout=30000)
    expect(page.locator('#fatal a[href="/"]')).to_be_visible()
    expect(page.locator("#talk-main")).to_be_hidden()
    page.screenshot(path=str(shot_dir / "two-page-expired.png"), full_page=True)


def test_busy_error(ctx: BrowserContext, base_url: str, shot_dir: Path) -> None:
    pg = ctx.new_page()
    pg.route(
        "**/turns/stream",
        lambda route: route.fulfill(
            status=503,
            content_type="application/json",
            body=json.dumps({"detail": {"code": "busy", "message": "busy"}}),
        ),
    )
    open_talk(pg, base_url, "preset-restaurant")
    pg.fill("#ask-input", "영업시간이 어떻게 돼요?")
    pg.click("#ask-btn")
    expect(pg.locator("#ask-error")).to_contain_text("잠시 뒤")
    pg.screenshot(path=str(shot_dir / "two-page-busy.png"), full_page=True)


def test_mic_denied(ctx: BrowserContext, base_url: str, shot_dir: Path) -> None:
    pg = ctx.new_page()

    def patch_options(route):  # type: ignore[no-untyped-def]
        resp = route.fetch()
        data = resp.json()
        data["voice_input_available"] = True
        route.fulfill(response=resp, body=json.dumps(data), content_type="application/json")

    pg.route("**/api/options", patch_options)
    pg.add_init_script(
        "navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('denied','NotAllowedError'))"
    )
    open_talk(pg, base_url, "preset-restaurant")
    expect(pg.locator("#mic-btn")).to_be_visible()
    pg.click("#mic-btn")
    expect(pg.locator("#ask-error")).to_contain_text("마이크")
    expect(pg.locator("#ask-input")).to_be_enabled()
    pg.screenshot(path=str(shot_dir / "two-page-mic-denied.png"), full_page=True)


def test_mobile_390(page: Page, base_url: str, shot_dir: Path) -> None:
    mobile = page.context.browser.new_context(viewport={"width": 390, "height": 844}, permissions=["microphone"])
    try:
        pg = mobile.new_page()
        open_home(pg, base_url)
        assert pg.evaluate("document.documentElement.scrollWidth") <= 390
        pg.screenshot(path=str(shot_dir / "two-page-mobile-home.png"), full_page=True)
        open_talk(pg, base_url, "preset-restaurant")
        ask(pg, "영업시간이 어떻게 돼요?")
        assert pg.evaluate("document.documentElement.scrollWidth") <= 390
        pg.screenshot(path=str(shot_dir / "two-page-mobile-talk.png"), full_page=True)
    finally:
        mobile.close()


def test_same_origin_only(ctx: BrowserContext, base_url: str) -> None:
    pg = ctx.new_page()
    urls: list[str] = []
    pg.on("request", lambda req: urls.append(req.url))
    open_home(pg, base_url)
    open_talk(pg, base_url, "preset-restaurant")
    external = [u for u in urls if u.startswith("http") and not u.startswith(base_url)]
    assert urls
    assert external == []


def test_no_engine_terms(page: Page, base_url: str) -> None:
    open_home(page, base_url)
    home_text = page.locator("body").inner_text()
    open_talk(page, base_url, "preset-restaurant")
    ask(page, "영업시간이 어떻게 돼요?")
    talk_text = page.locator("body").inner_text()
    for term in ENGINE_TERMS:
        assert term not in home_text, term
        assert term not in talk_text, term
