import re
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import BrowserContext, Page, expect

ROOT = Path(__file__).resolve().parents[2]
CSV_TEXT = (
    "질문,답변\n"
    "주차는 어디에 하나요?,지하 1층 주차장을 이용하세요. 두 시간 무료입니다.\n"
    "영업시간이 어떻게 되나요?,매일 오전 10시부터 오후 9시까지 영업합니다.\n"
    "휴무일은 언제인가요?,매주 월요일은 쉬는 날입니다.\n"
)
QUESTION = "등본 떼려면 뭐 필요해요?"


@pytest.fixture()
def make_agent(base_url: str) -> Iterator[Callable[[str, dict], str]]:
    ids: list[str] = []

    def make(name: str, knowledge: dict) -> str:
        r = httpx.post(
            f"{base_url}/api/agents", json={"name": name, "knowledge": knowledge}, timeout=30
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["agent_id"])
        return ids[-1]

    yield make
    for agent_id in ids:
        httpx.delete(f"{base_url}/api/agents/{agent_id}", timeout=30)


def new_page(page: Page, width: int, height: int, theme: str | None) -> Iterator[Page]:
    browser = page.context.browser
    ctx: BrowserContext = browser.new_context(viewport={"width": width, "height": height})
    if theme:
        ctx.add_init_script(f"localStorage.setItem('theme','{theme}')")
    pg = ctx.new_page()
    yield pg
    ctx.close()


def open_studio(pg: Page, base_url: str) -> None:
    pg.goto(f"{base_url}/studio")
    pg.wait_for_selector("body[data-ready=true]", timeout=30000)


def open_ws(pg: Page, base_url: str, agent: str) -> None:
    pg.goto(f"{base_url}/studio/app?agent={agent}")
    pg.wait_for_selector("body[data-ready=true]", timeout=30000)
    expect(pg.locator("#quota-count")).not_to_have_text(re.compile(r"^\s*(-|)\s*$"), timeout=30000)


def open_tab(pg: Page, tab: str) -> None:
    pg.click(f"#tab-btn-{tab}")
    expect(pg.locator(f"#tab-panel-{tab}")).to_be_visible()


def ask(pg: Page, question: str) -> None:
    pg.fill("#chat-textarea", question)
    pg.click("#send-btn")
    expect(pg.locator('.ws-turn[data-state="answered"]').first).to_be_visible(timeout=30000)


def shot(pg: Page, shot_dir: Path, name: str, full: bool = True) -> None:
    pg.screenshot(path=str(shot_dir / name), full_page=full)


def is_dark(pg: Page) -> bool:
    return bool(pg.evaluate("document.documentElement.classList.contains('dark')"))


def intersects(a: dict, b: dict) -> bool:
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


@pytest.mark.parametrize("size", [(1024, 768), (390, 844)], ids=["1024", "390"])
def test_toast_not_covering_delete_card(
    page: Page, base_url: str, shot_dir: Path, make_agent: Callable[[str, dict], str],
    size: tuple[int, int],
) -> None:  # fmt: skip
    agent = make_agent("토스트 상담원", {"kind": "faq_csv", "csv": CSV_TEXT})
    pg = next(new_page(page, size[0], size[1], "light"))
    open_ws(pg, base_url, agent)
    open_tab(pg, "settings")
    delete = pg.locator("#settings-delete-section")
    delete.scroll_into_view_if_needed()
    expect(delete).to_be_visible()
    pg.select_option("#setting-select-voice", index=1)
    delete.scroll_into_view_if_needed()
    pg.click("#settings-save-btn")
    toast = pg.locator("#toast-container").get_by_text("설정을 저장했습니다.")
    expect(toast).to_be_visible(timeout=10000)
    box_toast = pg.locator("#toast-container > *").first.bounding_box()
    box_delete = delete.bounding_box()
    box_header = pg.locator("body > header").first.bounding_box()
    assert box_toast and box_delete and box_header
    assert not intersects(box_toast, box_delete), (box_toast, box_delete)
    assert not intersects(box_toast, box_header), (box_toast, box_header)
    shot(pg, shot_dir, f"ws-toast-{size[0]}.png", full=False)
    pg.context.close()


def test_dark_captures(page: Page, base_url: str, shot_dir: Path) -> None:
    pg = next(new_page(page, 1024, 768, "dark"))
    open_studio(pg, base_url)
    assert is_dark(pg)
    shot(pg, shot_dir, "dark-studio-list.png")
    open_ws(pg, base_url, "preset-civil-kiosk")
    assert is_dark(pg)
    ask(pg, QUESTION)
    shot(pg, shot_dir, "dark-ws-chat.png")
    open_tab(pg, "knowledge")
    assert is_dark(pg)
    shot(pg, shot_dir, "dark-ws-knowledge.png")
    open_tab(pg, "settings")
    assert is_dark(pg)
    shot(pg, shot_dir, "dark-ws-settings.png")
    pg.context.close()


def test_knowledge_full_capture(
    page: Page, base_url: str, shot_dir: Path, make_agent: Callable[[str, dict], str]
) -> None:
    txt = (ROOT / "data" / "samples" / "fitness-center.txt").read_text(encoding="utf-8")
    agent = make_agent("피트니스 텍스트", {"kind": "text", "text": txt})
    pg = next(new_page(page, 1024, 768, "light"))
    open_ws(pg, base_url, agent)
    open_tab(pg, "knowledge")
    panel = pg.locator("#tab-panel-knowledge")
    expect(panel.get_by_text("운영 시간").first).to_be_visible(timeout=15000)
    panel.screenshot(path=str(shot_dir / "ws-knowledge-full.png"))
    pg.context.close()


def test_readme_shots(page: Page, base_url: str, shot_dir: Path) -> None:
    pg = next(new_page(page, 1280, 800, "light"))
    open_studio(pg, base_url)
    assert not is_dark(pg)
    shot(pg, shot_dir, "readme-studio-list.png")
    open_ws(pg, base_url, "preset-civil-kiosk")
    ask(pg, QUESTION)
    turn = pg.locator('.ws-turn[data-state="answered"]').first
    receipt = turn.locator("details.ws-receipt")
    if receipt.get_attribute("open") is None:
        receipt.locator("summary").click()
    expect(turn.locator(".ws-timings")).to_be_visible()
    shot(pg, shot_dir, "readme-ws-chat.png")
    pg.context.close()
    mob = next(new_page(page, 390, 844, "light"))
    open_ws(mob, base_url, "preset-civil-kiosk")
    shot(mob, shot_dir, "readme-mobile.png")
    mob.context.close()
