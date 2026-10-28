"""Public demo mode E2E (DEMO_MODE=1 server).

All tests share one visitor bucket on one server, so they run in definition
order and the number of violation responses (403/413/429) is kept low until
the last test, which deliberately triggers a temporary block.
"""

import json
import os
import re
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.environ.get("ILLY_BASE_URL", "http://localhost:8765")

if not httpx.get(f"{BASE_URL}/api/demo", timeout=10).json().get("demo_mode"):
    pytest.skip("demo mode is off on this server", allow_module_level=True)

CONTACT = os.environ.get("DEMO_EXPECT_CONTACT", "demo@example.com")
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) demo-e2e"
DEMO_KEYS = {
    "bucket", "contact", "demo_mode", "limits", "notice", "privacy_notice",
    "remaining", "reset_at", "token", "token_expires_in",
}  # fmt: skip
BANNER_TEXTS = (
    "데모 버전입니다",
    "완성된 기술이 필요하면 개발자에게 문의해 주세요",
    CONTACT,
    "외부 AI API로 전송됩니다",
)
PRESET = "preset-restaurant"
QUESTION = "영업시간이 어떻게 돼요?"
QUOTA_MESSAGE = "오늘 데모 사용 한도를 다 썼습니다"


# ---------- helpers ----------


def demo_info(base_url: str) -> dict:
    r = httpx.get(f"{base_url}/api/demo", headers={"User-Agent": BROWSER_UA}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()


def auth_headers(base_url: str) -> dict[str, str]:
    return {"User-Agent": BROWSER_UA, "X-Demo-Token": demo_info(base_url)["token"]}


def open_session(base_url: str, agent_id: str = PRESET) -> str:
    r = httpx.post(
        f"{base_url}/api/agents/{agent_id}/sessions", headers={"User-Agent": BROWSER_UA}, timeout=30
    )
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def stream_turn(base_url: str, agent_id: str, session_id: str, text: str) -> httpx.Response:
    return httpx.post(
        f"{base_url}/api/agents/{agent_id}/turns/stream",
        headers=auth_headers(base_url),
        json={"session_id": session_id, "text": text},
        timeout=60,
    )


def sse_events(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        if name and data:
            events.append((name, json.loads(data)))
    return events


def open_studio(pg: Page, base_url: str) -> None:
    pg.goto(f"{base_url}/studio")
    pg.wait_for_selector("body[data-ready=true]", timeout=30000)


def open_ws(pg: Page, base_url: str, agent: str = PRESET) -> None:
    pg.goto(f"{base_url}/studio/app?agent={agent}")
    pg.wait_for_selector("body[data-ready=true]", timeout=30000)
    expect(pg.locator("#quota-count")).to_have_text(re.compile(r"^\s*\d+\s*$"), timeout=30000)


def check_banner(pg: Page, shot_dir: Path, name: str, width: int, height: int) -> None:
    pg.set_viewport_size({"width": width, "height": height})
    banner = pg.locator("[data-demo-banner]")
    banner.wait_for(state="visible", timeout=30000)
    text = banner.inner_text()
    for needle in BANNER_TEXTS:
        assert needle in text, f"missing {needle!r} in banner: {text!r}"
    assert pg.locator("[data-demo-remaining]").count() == 1
    hit = pg.evaluate(
        """() => {
            const b = document.querySelector('[data-demo-banner]');
            const r = b.getBoundingClientRect();
            const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
            return !!el && b.contains(el);
        }"""
    )
    assert hit, "element at banner center is not inside the banner"
    assert pg.locator('a[href="/docs"]:visible').count() == 0
    pg.screenshot(path=str(shot_dir / f"demo-{name}.png"), full_page=True)


# ---------- tests (definition order matters) ----------


def test_public_demo_info(base_url: str) -> None:
    data = demo_info(base_url)
    assert set(data) == DEMO_KEYS
    assert data["demo_mode"] is True
    assert data["contact"] == CONTACT
    assert re.fullmatch(r"[0-9a-f]{16}", data["bucket"])
    assert re.fullmatch(r"\d+\.[0-9a-f]{32}", data["token"])
    assert data["token_expires_in"] == 1800


def test_public_banner_studio(page: Page, base_url: str, shot_dir: Path) -> None:
    page.set_viewport_size({"width": 1024, "height": 768})
    open_studio(page, base_url)
    check_banner(page, shot_dir, "studio-1024", 1024, 768)
    page.goto(f"{base_url}/studio")
    page.wait_for_selector("body[data-ready=true]", timeout=30000)
    check_banner(page, shot_dir, "studio-390", 390, 844)
    page.set_viewport_size({"width": 1024, "height": 768})


def test_public_banner_workspace(page: Page, base_url: str, shot_dir: Path) -> None:
    page.set_viewport_size({"width": 1024, "height": 768})
    open_ws(page, base_url)
    check_banner(page, shot_dir, "workspace-1024", 1024, 768)
    open_ws(page, base_url)
    check_banner(page, shot_dir, "workspace-390", 390, 844)
    page.set_viewport_size({"width": 1024, "height": 768})


def test_public_studio_question_flow(page: Page, base_url: str) -> None:
    page.set_viewport_size({"width": 1024, "height": 768})
    bad: list[str] = []

    def on_response(resp) -> None:  # type: ignore[no-untyped-def]
        if resp.status in (403, 404):
            bad.append(f"{resp.status} {resp.url}")

    page.on("response", on_response)
    try:
        open_studio(page, base_url)
        open_ws(page, base_url)
        page.fill("#chat-textarea", QUESTION)
        page.click("#send-btn")
        answered = page.locator('.ws-turn[data-state="answered"]').first
        answered.wait_for(state="visible", timeout=30000)
        assert answered.locator(".ws-sentence").count() >= 1
        assert answered.locator(".ws-sentence").first.inner_text().strip()
    finally:
        page.remove_listener("response", on_response)
    assert bad == [], f"page received error responses: {bad}"


def test_public_hidden_surface(base_url: str) -> None:
    for path in ("/docs", "/redoc", "/openapi.json", "/static/archive/kiosk/index.html"):
        r = httpx.get(f"{base_url}{path}", headers={"User-Agent": BROWSER_UA}, timeout=10)
        assert r.status_code == 404, f"{path} -> {r.status_code}"
    r = httpx.post(
        f"{base_url}/api/ask",
        headers={"User-Agent": BROWSER_UA},
        json={"text": QUESTION},
        timeout=10,
    )
    assert r.status_code == 404


def test_public_security_headers(base_url: str) -> None:
    origin = {"Origin": "https://evil.example", "User-Agent": BROWSER_UA}
    for path in ("/studio", "/api/options"):
        r = httpx.get(f"{base_url}{path}", headers=origin, timeout=10)
        assert r.status_code == 200, path
        assert r.headers.get("content-security-policy"), path
        assert r.headers.get("x-content-type-options") == "nosniff", path
        assert r.headers.get("referrer-policy") == "no-referrer", path
        assert r.headers.get("permissions-policy"), path
        assert "access-control-allow-origin" not in r.headers, path


def test_public_no_csp_violation(page: Page, base_url: str) -> None:
    page.set_viewport_size({"width": 1024, "height": 768})
    messages: list[str] = []

    def on_console(msg) -> None:  # type: ignore[no-untyped-def]
        messages.append(msg.text)

    page.on("console", on_console)
    try:
        open_studio(page, base_url)
        open_ws(page, base_url)
    finally:
        page.remove_listener("console", on_console)
    csp = [m for m in messages if "Content Security Policy" in m]
    assert csp == []


def test_public_spoofed_xff_same_bucket(base_url: str) -> None:
    buckets = set()
    for xff in ("2001:db8::1", "2001:db8:ffff::9"):
        r = httpx.get(
            f"{base_url}/api/demo",
            headers={"User-Agent": BROWSER_UA, "X-Forwarded-For": xff},
            timeout=10,
        )
        assert r.status_code == 200
        buckets.add(r.json()["bucket"])
    assert len(buckets) == 1
    assert buckets == {demo_info(base_url)["bucket"]}


def test_bot_missing_token(base_url: str) -> None:
    session_id = open_session(base_url)
    before = demo_info(base_url)["remaining"]["turns"]
    r = httpx.post(
        f"{base_url}/api/agents/{PRESET}/turns/stream",
        headers={"User-Agent": BROWSER_UA},
        json={"session_id": session_id, "text": QUESTION},
        timeout=30,
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "demo_token_required"
    assert demo_info(base_url)["remaining"]["turns"] == before


def test_bot_script_ua(base_url: str) -> None:
    r = httpx.post(
        f"{base_url}/api/agents",
        headers={"User-Agent": "curl/8.0", "Content-Type": "application/json"},
        content="{}",
        timeout=10,
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "automated_client"
    h = httpx.get(f"{base_url}/health", headers={"User-Agent": "curl/8.0"}, timeout=10)
    assert h.status_code == 200


def test_quota_turns_exhausted(base_url: str) -> None:
    remaining = demo_info(base_url)["remaining"]["turns"]
    assert remaining >= 1, "earlier tests used more turns than planned"
    session_id = open_session(base_url)
    for i in range(remaining):
        r = stream_turn(base_url, PRESET, session_id, QUESTION)
        assert r.status_code == 200, f"turn {i}: {r.status_code} {r.text}"
        assert any(name == "done" for name, _ in sse_events(r.text))
    r = stream_turn(base_url, PRESET, session_id, QUESTION)
    assert r.status_code == 429
    detail = r.json()["detail"]
    assert detail["code"] == "demo_quota_exceeded"
    assert detail["kind"] == "turns"
    assert demo_info(base_url)["remaining"]["turns"] == 0


def test_quota_toast_ui(page: Page, base_url: str, shot_dir: Path) -> None:
    page.set_viewport_size({"width": 1024, "height": 768})
    open_ws(page, base_url)
    page.fill("#chat-textarea", QUESTION)
    page.click("#send-btn")
    # The server message is shown in the workspace error area (and on the failed turn).
    msg = page.get_by_text(QUOTA_MESSAGE).first
    msg.wait_for(state="visible", timeout=30000)
    page.screenshot(path=str(shot_dir / "demo-quota-toast.png"), full_page=True)


def test_payload_too_large(base_url: str) -> None:
    r = httpx.post(
        f"{base_url}/api/agents",
        headers={**auth_headers(base_url), "Content-Type": "application/json"},
        content=b'{"name":"' + b"a" * (600 * 1024) + b'"}',
        timeout=30,
    )
    assert r.status_code == 413
    assert r.json()["detail"]["code"] == "payload_too_large"


def test_bot_escalating_block(base_url: str) -> None:
    blocked: httpx.Response | None = None
    for _ in range(12):
        r = httpx.post(
            f"{base_url}/api/agents/{PRESET}/turns/stream",
            headers={"User-Agent": BROWSER_UA},
            json={"session_id": "s_000000000000", "text": QUESTION},
            timeout=10,
        )
        if r.status_code == 429 and r.json()["detail"]["code"] == "temporarily_blocked":
            blocked = r
            break
        assert r.status_code == 403, r.text
    assert blocked is not None, "no temporarily_blocked within 12 requests"
    assert blocked.headers.get("retry-after"), "Retry-After header missing"
    assert 0 < int(blocked.headers["retry-after"]) <= 600
    retry_after = blocked.json()["detail"]["retry_after"]
    assert 0 < retry_after <= 600
    after = httpx.get(f"{base_url}/api/demo", headers={"User-Agent": BROWSER_UA}, timeout=10)
    assert after.status_code == 429


def test_live_llm_summary(base_url: str) -> None:
    ua = {"User-Agent": BROWSER_UA}
    opts = httpx.get(f"{base_url}/api/options", headers=ua, timeout=10).json()
    assert opts["summary_available"] is True, "LLM summary is not available (key missing?)"
    assert opts["defaults"]["summary"] is True
    presets = httpx.get(f"{base_url}/api/presets", headers=ua, timeout=10).json()["items"]
    first = presets[0]
    agent = httpx.get(f"{base_url}/api/agents/{first['agent_id']}", headers=ua, timeout=10).json()
    assert agent["settings"]["summary"] is True
    question = first["sample_questions"][0]
    session_id = open_session(base_url, first["agent_id"])
    r = stream_turn(base_url, first["agent_id"], session_id, question)
    assert r.status_code == 200, r.text
    done = [d for name, d in sse_events(r.text) if name == "done"]
    assert done and done[0]["summary_used"] is True
    c = httpx.post(
        f"{base_url}/api/agents/{first['agent_id']}/compare",
        headers=auth_headers(base_url),
        json={
            "session_id": session_id,
            "question": question,
            "a": {"summary": False},
            "b": {"summary": True},
        },
        timeout=90,
    )
    assert c.status_code == 200, c.text
    body = c.json()
    assert body["b"]["summary_used"] is True
    assert body["b"]["answer"] != body["a"]["answer"]
