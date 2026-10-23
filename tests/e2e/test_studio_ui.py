import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import BrowserContext, Page, Route, expect

CSV_TEXT = (
    "질문,답변\n"
    "주차는 어디에 하나요?,지하 1층 주차장을 이용하세요. 두 시간 무료입니다. 정산은 출구에서 합니다.\n"
    "영업시간이 어떻게 되나요?,매일 오전 10시부터 오후 9시까지 영업합니다.\n"
    "반려동물 동반이 가능한가요?,소형 반려동물은 이동 가방에 넣으면 입장할 수 있습니다.\n"
    "와이파이 비밀번호가 무엇인가요?,계산대에서 안내 카드를 받아 가세요.\n"
    "휴무일은 언제인가요?,매주 월요일은 쉬는 날입니다.\n"
)
TABS = ("conversation", "knowledge", "settings", "scorecard", "abtest")
FORBIDDEN = (
    "Mock", "mock", "RAG", "청크", "TTFT", "TTS", "STT", "LLM", "Whisper", "ElevenLabs", "OpenAI",
    "WebRTC", "WebSocket", "99.9", "320ms", "A+", "김엔지니어",
)  # fmt: skip
QUESTION = "영업시간이 어떻게 돼요?"
AGENT_ID_RE = re.compile(r"ag_[0-9a-f]{12}")


@pytest.fixture()
def ctx(page: Page) -> Iterator[BrowserContext]:
    c = page.context.browser.new_context(
        viewport={"width": 1024, "height": 768}, permissions=["microphone"]
    )
    yield c
    c.close()


@pytest.fixture()
def pg(ctx: BrowserContext) -> Page:
    return ctx.new_page()


@pytest.fixture()
def make_agent(base_url: str) -> Iterator[Callable[..., str]]:
    ids: list[str] = []

    def make(name: str = "테스트 상담원", settings: dict | None = None) -> str:
        body: dict = {"name": name, "knowledge": {"kind": "faq_csv", "csv": CSV_TEXT}}
        if settings:
            body["settings"] = settings
        r = httpx.post(f"{base_url}/api/agents", json=body, timeout=30)
        assert r.status_code == 201, r.text
        ids.append(r.json()["agent_id"])
        return ids[-1]

    yield make
    for agent_id in ids:
        httpx.delete(f"{base_url}/api/agents/{agent_id}", timeout=30)


@pytest.fixture()
def track_agent(base_url: str) -> Iterator[Callable[[str], None]]:
    ids: list[str] = []
    yield ids.append
    for agent_id in ids:
        httpx.delete(f"{base_url}/api/agents/{agent_id}", timeout=30)


def open_studio(pg: Page, base_url: str) -> None:
    pg.goto(f"{base_url}/studio")
    pg.wait_for_selector("body[data-ready=true]", timeout=30000)


def open_ws(pg: Page, base_url: str, agent: str) -> None:
    pg.goto(f"{base_url}/studio/app?agent={agent}")
    pg.wait_for_selector("body[data-ready=true]", timeout=30000)
    expect(pg.locator("#quota-count")).not_to_have_text(re.compile(r"^\s*(-|)\s*$"), timeout=30000)


def quota(pg: Page) -> int:
    return int(pg.locator("#quota-count").inner_text().strip())


def open_tab(pg: Page, tab: str) -> None:
    pg.click(f"#tab-btn-{tab}")
    expect(pg.locator(f"#tab-panel-{tab}")).to_be_visible()


def ask(pg: Page, question: str) -> None:
    pg.fill("#chat-textarea", question)
    pg.click("#send-btn")
    expect(pg.locator('.ws-turn[data-state="answered"]').first).to_be_visible(timeout=30000)


def fulfill_json(status: int, code: str, message: str) -> Callable[[Route], None]:
    def handler(route: Route) -> None:
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps({"detail": {"code": code, "message": message}}),
        )

    return handler


def voice_available(base_url: str) -> bool:
    return bool(httpx.get(f"{base_url}/api/options", timeout=10).json()["voice_input_available"])


def preset_chunk_count(base_url: str, preset_id: str) -> int:
    data = httpx.get(f"{base_url}/api/presets", timeout=10).json()
    return next(p["chunk_count"] for p in data["items"] if p["preset_id"] == preset_id)


def cards(pg: Page):  # type: ignore[no-untyped-def]
    return pg.locator("#agents-grid article.studio-card:visible")


def test_studio_list_and_filter(pg: Page, base_url: str, shot_dir: Path) -> None:
    open_studio(pg, base_url)
    expect(cards(pg)).to_have_count(4)
    expect(pg.locator("#api-health-badge")).to_have_attribute("data-health", "ok")
    pg.click('#category-filter-group button[data-category="hospital"]')
    expect(cards(pg)).to_have_count(1)
    expect(cards(pg).first).to_have_attribute("data-preset-id", "hospital")
    pg.screenshot(path=str(shot_dir / "studio-list.png"), full_page=True)


def test_studio_search_empty(pg: Page, base_url: str, shot_dir: Path) -> None:
    open_studio(pg, base_url)
    pg.fill("#agent-search-input", "존재하지않는검색어")
    expect(pg.locator("#no-results-view")).to_be_visible()
    expect(cards(pg)).to_have_count(0)
    pg.screenshot(path=str(shot_dir / "studio-empty.png"), full_page=True)
    pg.click("#btn-reset-filters")
    expect(cards(pg)).to_have_count(4)


def test_studio_presets_error_retry(pg: Page, base_url: str, shot_dir: Path) -> None:
    pg.route("**/api/presets", lambda route: route.abort())
    open_studio(pg, base_url)
    expect(pg.locator("#error-view")).to_be_visible()
    expect(cards(pg)).to_have_count(0)
    pg.screenshot(path=str(shot_dir / "studio-error.png"), full_page=True)
    pg.unroute("**/api/presets")
    pg.click("#btn-retry-fetch")
    expect(cards(pg)).to_have_count(4)


def test_create_empty_rejected(pg: Page, base_url: str, shot_dir: Path) -> None:
    open_studio(pg, base_url)
    pg.click("#btn-hero-create")
    expect(pg.locator("#create-agent-modal")).to_be_visible()
    pg.fill("#text-knowledge-input", "")
    pg.click("#modal-submit-btn")
    expect(pg.locator("#modal-error-box")).to_be_visible()
    expect(pg.locator("#modal-error-box")).not_to_be_empty()
    assert pg.url.rstrip("/").endswith("/studio")
    pg.screenshot(path=str(shot_dir / "studio-create-error.png"), full_page=True)


def test_csv_create_to_workspace(
    pg: Page, base_url: str, shot_dir: Path, track_agent: Callable[[str], None]
) -> None:
    open_studio(pg, base_url)
    pg.click("#btn-hero-create")
    pg.click("#tab-mode-csv")
    pg.set_input_files(
        "#csv-file-input",
        files=[{"name": "faq.csv", "mimeType": "text/csv", "buffer": CSV_TEXT.encode()}],
    )
    pg.fill("#modal-agent-name", "우리 가게 상담원")
    pg.screenshot(path=str(shot_dir / "studio-create-modal.png"), full_page=True)
    pg.click("#modal-submit-btn")
    pg.wait_for_url(re.compile(r"/studio/app\?agent=ag_[0-9a-f]{12}"), timeout=30000)
    match = AGENT_ID_RE.search(pg.url)
    assert match
    track_agent(match.group(0))
    pg.wait_for_selector("body[data-ready=true]", timeout=30000)
    ask(pg, "영업시간이 어떻게 되나요?")
    expect(pg.locator(".ws-turn .ws-sentence").first).to_contain_text("오전 10시")
    pg.screenshot(path=str(shot_dir / "ws-custom-chat.png"), full_page=True)
    pg.goto(f"{base_url}/studio")
    pg.wait_for_selector("body[data-ready=true]", timeout=30000)
    expect(pg.locator('#agents-grid article.studio-card[data-custom="true"]')).to_have_count(1)


def test_preset_chat_receipt(pg: Page, base_url: str, shot_dir: Path) -> None:
    open_ws(pg, base_url, "preset-civil-kiosk")
    before = quota(pg)
    pg.locator("#sample-chips-container button.sample-chip").first.click()
    turn = pg.locator('.ws-turn[data-state="answered"]').first
    expect(turn).to_be_visible(timeout=30000)
    receipt = turn.locator("details.ws-receipt")
    expect(receipt).to_have_attribute("open", "")
    expect(turn.locator(".ws-timings")).to_contain_text("첫 음성까지")
    expect(turn.locator(".ws-candidates")).to_contain_text("점수")
    assert turn.locator(".ws-sentence").count() >= 1
    expect(pg.locator("#quota-count")).to_have_text(str(before - 1))
    pg.screenshot(path=str(shot_dir / "ws-chat-receipt.png"), full_page=True)
    receipt.locator("summary").click()
    expect(turn.locator(".ws-timings")).to_be_hidden()


def test_evidence_link_opens_knowledge(pg: Page, base_url: str, shot_dir: Path) -> None:
    open_ws(pg, base_url, "preset-civil-kiosk")
    ask(pg, "등본 떼려면 뭐 필요해요?")
    pg.locator("a.ws-evidence-link").first.click()
    expect(pg.locator("#tab-panel-knowledge")).to_be_visible()
    expect(pg.locator('li.ws-chunk[data-focused="true"]')).to_have_count(1)
    pg.screenshot(path=str(shot_dir / "ws-evidence-focus.png"), full_page=True)


def test_knowledge_paging(pg: Page, base_url: str, shot_dir: Path) -> None:
    count = preset_chunk_count(base_url, "civil-kiosk")
    assert count > 100
    open_ws(pg, base_url, "preset-civil-kiosk")
    open_tab(pg, "knowledge")
    expect(pg.locator("#knowledge-chunk-list li.ws-chunk")).to_have_count(50)
    expect(pg.locator("#knowledge-chunk-counter")).to_contain_text(str(count))
    pg.screenshot(path=str(shot_dir / "ws-knowledge.png"), full_page=True)
    pg.click("#knowledge-load-more-btn")
    expect(pg.locator("#knowledge-chunk-list li.ws-chunk")).to_have_count(100)


def test_settings_preset_readonly(pg: Page, base_url: str, shot_dir: Path) -> None:
    open_ws(pg, base_url, "preset-restaurant")
    open_tab(pg, "settings")
    expect(pg.locator("#settings-save-btn")).to_be_hidden()
    expect(pg.locator("#setting-input-tone")).to_be_disabled()
    pg.click("#more-menu-btn")
    expect(pg.locator("#menu-delete-agent")).to_be_hidden()
    pg.keyboard.press("Escape")
    pg.screenshot(path=str(shot_dir / "ws-settings-preset.png"), full_page=True)


def test_settings_custom_save(
    pg: Page, base_url: str, shot_dir: Path, make_agent: Callable[..., str]
) -> None:
    agent = make_agent()
    open_ws(pg, base_url, agent)
    open_tab(pg, "settings")
    pg.select_option("#setting-input-length", "detailed")
    pg.click("#settings-save-btn")
    expect(pg.locator("#settings-error")).to_be_hidden()
    pg.screenshot(path=str(shot_dir / "ws-settings-custom.png"), full_page=True)
    assert (
        httpx.get(f"{base_url}/api/agents/{agent}", timeout=10).json()["settings"]["answer_length"]
        == "detailed"
    )
    pg.reload()
    pg.wait_for_selector("body[data-ready=true]", timeout=30000)
    open_tab(pg, "settings")
    expect(pg.locator("#setting-input-length")).to_have_value("detailed")
    expect(pg.locator("#setting-input-length option:checked")).to_have_text("자세히")


def test_scorecard_restaurant(pg: Page, base_url: str, shot_dir: Path) -> None:
    open_ws(pg, base_url, "preset-restaurant")
    open_tab(pg, "scorecard")
    pg.select_option("#scorecard-n", "10")
    pg.click("#scorecard-start-btn")
    expect(pg.locator("#scorecard-report")).to_be_visible(timeout=180000)
    assert re.search(r"\d+\s*/\s*\d+", pg.locator("#sc-text-hits").inner_text())
    expect(pg.locator("#sc-caveat")).not_to_be_empty()
    pg.screenshot(path=str(shot_dir / "ws-scorecard.png"), full_page=True)


def test_ab_compare(pg: Page, base_url: str, shot_dir: Path) -> None:
    open_ws(pg, base_url, "preset-restaurant")
    before = quota(pg)
    open_tab(pg, "abtest")
    pg.fill("#ab-question", QUESTION)
    pg.select_option("#ab-a-length", "one_sentence")
    pg.select_option("#ab-b-length", "detailed")
    pg.click("#ab-run-btn")
    expect(pg.locator("#ab-result")).to_be_visible(timeout=60000)
    assert pg.locator("#ab-col-a .ab-answer").inner_text().strip()
    assert pg.locator("#ab-col-b .ab-answer").inner_text().strip()
    assert pg.locator("#ab-col-a .ab-sentence-count").inner_text().strip()
    assert pg.locator("#ab-col-b .ab-sentence-count").inner_text().strip()
    assert pg.locator("#ab-notes li").count() >= 1
    expect(pg.locator("#quota-count")).to_have_text(str(before - 1))
    pg.screenshot(path=str(shot_dir / "ws-compare.png"), full_page=True)


def test_share_link_fresh_context(
    pg: Page, ctx: BrowserContext, base_url: str, shot_dir: Path, make_agent: Callable[..., str]
) -> None:
    agent = make_agent("우리 가게 상담원")
    open_ws(pg, base_url, agent)
    pg.click("#share-btn")
    link = pg.locator("#share-url-input").input_value()
    assert f"/studio/app?agent={agent}" in link
    other = ctx.browser.new_context(viewport={"width": 1024, "height": 768})  # type: ignore[union-attr]
    try:
        op = other.new_page()
        op.goto(link)
        op.wait_for_selector("body[data-ready=true]", timeout=30000)
        expect(op.locator("#top-agent-name")).to_have_text("우리 가게 상담원")
        expect(op.locator("#quota-count")).to_have_text("30")
        op.screenshot(path=str(shot_dir / "ws-share.png"), full_page=True)
    finally:
        other.close()


def test_old_talk_link_redirects(pg: Page, base_url: str) -> None:
    pg.goto(f"{base_url}/talk?agent=preset-civil-kiosk")
    pg.wait_for_url(re.compile(r"/studio/app\?agent=preset-civil-kiosk$"))
    pg.wait_for_selector("body[data-ready=true]", timeout=30000)
    expect(pg.locator("#top-agent-name")).to_contain_text("민원 키오스크")


def test_unknown_agent_recovery(pg: Page, base_url: str, shot_dir: Path) -> None:
    pg.goto(f"{base_url}/studio/app?agent=ag_000000000000")
    expect(pg.locator("#agent-recovery-card")).to_be_visible(timeout=30000)
    expect(pg.locator('a#recovery-back[href="/studio"]')).to_be_visible()
    expect(pg.locator("#chat-form")).to_be_hidden()
    pg.screenshot(path=str(shot_dir / "ws-error-404.png"), full_page=True)


def test_agent_load_network_error(pg: Page, base_url: str, shot_dir: Path) -> None:
    pg.route("**/api/agents/preset-restaurant", lambda route: route.abort())
    pg.goto(f"{base_url}/studio/app?agent=preset-restaurant")
    expect(pg.locator("#agent-error-state")).to_be_visible(timeout=30000)
    expect(pg.locator("#chat-form")).to_be_hidden()
    pg.screenshot(path=str(shot_dir / "ws-error-network.png"), full_page=True)


def test_busy_error(pg: Page, base_url: str, shot_dir: Path) -> None:
    pg.route("**/turns/stream", fulfill_json(503, "busy", "busy"))
    open_ws(pg, base_url, "preset-restaurant")
    pg.fill("#chat-textarea", QUESTION)
    pg.click("#send-btn")
    expect(pg.locator("#chat-error")).to_contain_text("잠시 뒤")
    pg.screenshot(path=str(shot_dir / "ws-busy.png"), full_page=True)


def test_question_limit(pg: Page, base_url: str) -> None:
    pg.route("**/turns/stream", fulfill_json(429, "question_limit", "limit"))
    open_ws(pg, base_url, "preset-restaurant")
    pg.fill("#chat-textarea", QUESTION)
    pg.click("#send-btn")
    expect(pg.locator("#chat-error")).to_contain_text("질문 수")


def test_mic_denied_or_hidden(pg: Page, base_url: str, shot_dir: Path) -> None:
    if voice_available(base_url):
        pg.add_init_script(
            "navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('denied','NotAllowedError'))"
        )
        open_ws(pg, base_url, "preset-restaurant")
        expect(pg.locator("#mic-btn")).to_be_visible()
        pg.click("#mic-btn")
        expect(pg.locator("#chat-error")).to_contain_text("마이크")
        expect(pg.locator("#chat-textarea")).to_be_enabled()
    else:
        open_ws(pg, base_url, "preset-restaurant")
        expect(pg.locator("#mic-btn")).to_be_hidden()
        expect(pg.locator("#mic-hint")).to_contain_text("글자로")
    pg.screenshot(path=str(shot_dir / "ws-mic.png"), full_page=True)


def test_delete_custom_agent(pg: Page, base_url: str, make_agent: Callable[..., str]) -> None:
    agent = make_agent()
    open_ws(pg, base_url, agent)
    pg.once("dialog", lambda d: d.accept())
    pg.click("#more-menu-btn")
    pg.click("#menu-delete-agent")
    pg.wait_for_url(re.compile(r"/studio/?$"), timeout=30000)
    pg.wait_for_selector("body[data-ready=true]", timeout=30000)
    expect(pg.locator(f'#agents-grid article[data-agent-id="{agent}"]')).to_have_count(0)
    assert httpx.get(f"{base_url}/api/agents/{agent}", timeout=10).status_code == 404


def test_mobile_390(page: Page, base_url: str, shot_dir: Path) -> None:
    mobile = page.context.browser.new_context(
        viewport={"width": 390, "height": 844}, permissions=["microphone"]
    )
    try:
        pg = mobile.new_page()
        open_studio(pg, base_url)
        assert pg.evaluate("document.documentElement.scrollWidth") <= 390
        pg.screenshot(path=str(shot_dir / "studio-mobile.png"), full_page=True)
        open_ws(pg, base_url, "preset-restaurant")
        ask(pg, QUESTION)
        assert pg.evaluate("document.documentElement.scrollWidth") <= 390
        pg.screenshot(path=str(shot_dir / "ws-mobile.png"), full_page=True)
    finally:
        mobile.close()


def test_same_origin_only(pg: Page, base_url: str) -> None:
    urls: list[str] = []
    pg.on("request", lambda req: urls.append(req.url))
    open_studio(pg, base_url)
    open_ws(pg, base_url, "preset-restaurant")
    external = [u for u in urls if u.startswith("http") and not u.startswith(base_url)]
    assert urls
    assert external == []


def test_no_engine_or_mock_terms(pg: Page, base_url: str) -> None:
    open_studio(pg, base_url)
    texts = {"studio": pg.locator("body").inner_text()}
    open_ws(pg, base_url, "preset-restaurant")
    for tab in TABS:
        open_tab(pg, tab)
        texts[tab] = pg.locator("body").inner_text()
    for where, text in texts.items():
        for term in FORBIDDEN:
            assert term not in text, (where, term)


def test_icons_render(pg: Page, base_url: str) -> None:
    js = "[...document.querySelectorAll('.material-symbols-outlined')].map(e => e.getBoundingClientRect().width)"
    open_studio(pg, base_url)
    studio_widths = pg.evaluate(js)
    open_ws(pg, base_url, "preset-restaurant")
    ws_widths = pg.evaluate(js)
    assert studio_widths and ws_widths
    assert max(studio_widths) <= 48
    assert max(ws_widths) <= 48
