import base64
import io
import json
import time
import wave
from pathlib import Path

import pytest
from playwright.sync_api import Page, Route

ERR_STREAM = "답변을 가져오지 못했습니다."


def silent_wav_b64(seconds: float, rate: int = 16000) -> str:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return base64.b64encode(buf.getvalue()).decode()


WAV_FIRST = silent_wav_b64(5.0)
WAV_SECOND = silent_wav_b64(1.0)


def sse(*events: tuple[str, dict]) -> str:
    return "".join(f"event: {n}\ndata: {json.dumps(d, ensure_ascii=False)}\n\n" for n, d in events)


def answer_events(tag: str, sentence: str, wav_b64: str, with_done: bool = True) -> str:
    evs: list[tuple[str, dict]] = [
        ("meta", {"transcript": f"질문 {tag}", "answer": sentence, "source": None,
                  "sentence_count": 1}),
        ("audio", {"index": 0, "text": sentence, "audio_wav_b64": wav_b64, "elapsed_ms": 10}),
    ]
    if with_done:
        evs.append(("done", {"sentence_count": 1, "timings": {
            "stt_ms": 0, "retrieve_ms": 1, "llm_ms": 1, "tts_ms": 1,
            "first_audio_ms": 10, "total_ms": 20}}))
    return sse(*evs)


def fulfill_sse(route: Route, body: str, status: int = 200) -> None:
    route.fulfill(status=status, content_type="text/event-stream", body=body)


@pytest.fixture(autouse=True)
def clean_session_page(page: Page):
    # session-scoped `page` is shared with other modules: drop our routes after each test
    yield
    page.unroute_all()
    page.goto("about:blank")


@pytest.fixture()
def autoplay_page(page: Page):
    # The session `page` fixture owns the running sync Playwright; reuse its browser type
    # instead of starting a second sync_playwright() (not allowed while one is active).
    browser_type = page.context.browser.browser_type
    browser = browser_type.launch(
        headless=True, args=["--autoplay-policy=no-user-gesture-required"]
    )
    pg = browser.new_page(viewport={"width": 1024, "height": 768})
    yield pg
    pg.close()
    browser.close()


def ask(page: Page, text: str) -> None:
    page.fill("#question", text)
    page.click("#ask")


def test_new_question_stops_previous_audio(autoplay_page: Page, base_url: str, shot_dir: Path) -> None:
    page = autoplay_page
    calls = {"n": 0}

    def handler(route: Route) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            fulfill_sse(route, answer_events("1", "첫번째 답변입니다.", WAV_FIRST))
        else:
            fulfill_sse(route, answer_events("2", "두번째 답변입니다.", WAV_SECOND))

    page.route("**/api/ask-stream", handler)
    page.goto(base_url)
    ask(page, "첫 질문")
    page.wait_for_selector('#result[data-state="answered"]', timeout=15000)
    page.wait_for_function("document.getElementById('audio').paused === false", timeout=10000)

    paused_after_click = page.evaluate(
        """() => {
            document.getElementById('question').value = '둘째 질문';
            document.getElementById('ask').click();
            return document.getElementById('audio').paused;
        }"""
    )
    assert paused_after_click is True

    page.wait_for_function(
        "document.getElementById('sentences').textContent.includes('두번째')", timeout=15000
    )
    page.wait_for_selector('#result[data-state="answered"]', timeout=15000)
    second_src = f"data:audio/wav;base64,{WAV_SECOND}"
    assert page.evaluate("document.getElementById('audio').src") == second_src
    items = page.locator("#sentences li").all_inner_texts()
    assert items == ["두번째 답변입니다."]
    page.screenshot(path=str(shot_dir / "demo-playback-second.png"), full_page=True)


def test_late_audio_of_old_request_ignored(autoplay_page: Page, base_url: str) -> None:
    page = autoplay_page
    pending: list[Route] = []
    calls = {"n": 0}

    def handler(route: Route) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            pending.append(route)  # hold the first response until after the second click
        else:
            fulfill_sse(route, answer_events("2", "두번째 답변입니다.", WAV_SECOND))

    page.route("**/api/ask-stream", handler)
    page.goto(base_url)
    ask(page, "첫 질문")
    page.wait_for_selector('#result[data-state="loading"]', timeout=5000)
    deadline = time.monotonic() + 10
    while not pending and time.monotonic() < deadline:
        page.wait_for_timeout(50)  # pump the sync Playwright loop so the route handler runs
    assert pending, "first request never reached the route"
    # #ask is disabled while the first request is pending; Enter in the input still submits
    page.fill("#question", "둘째 질문")
    page.press("#question", "Enter")
    page.wait_for_selector('#result[data-state="answered"]', timeout=15000)

    fulfill_sse(pending[0], answer_events("1", "첫번째 답변입니다.", WAV_FIRST))
    # negative assertion: give the stale stream time to (wrongly) render, then check
    page.wait_for_timeout(500)
    text = page.locator("#result").inner_text()
    assert "두번째 답변입니다." in text
    assert "첫번째" not in text
    assert page.locator("#sentences li").all_inner_texts() == ["두번째 답변입니다."]
    assert page.locator("#result").get_attribute("data-state") == "answered"


def test_stream_error_event_shows_error(page: Page, base_url: str, shot_dir: Path) -> None:
    page.route(
        "**/api/ask-stream",
        lambda r: fulfill_sse(r, sse(("error", {"detail": "boom"}))),
    )
    page.goto(base_url)
    ask(page, "아무 질문")
    page.wait_for_selector('#result[data-state="error"]', timeout=15000)
    assert ERR_STREAM in page.locator("#error").inner_text()
    page.screenshot(path=str(shot_dir / "demo-error-stream.png"), full_page=True)


def test_stream_without_done_shows_error(page: Page, base_url: str) -> None:
    page.route(
        "**/api/ask-stream",
        lambda r: fulfill_sse(r, answer_events("1", "끊긴 답변입니다.", WAV_SECOND, with_done=False)),
    )
    page.goto(base_url)
    ask(page, "아무 질문")
    page.wait_for_selector('#result[data-state="error"]', timeout=15000)
    assert ERR_STREAM in page.locator("#error").inner_text()


def test_network_abort_shows_error(page: Page, base_url: str) -> None:
    page.route("**/api/ask-stream", lambda r: r.abort())
    page.goto(base_url)
    ask(page, "아무 질문")
    page.wait_for_selector('#result[data-state="error"]', timeout=15000)
    assert "서버에 연결하지 못했습니다." in page.locator("#error").inner_text()


def test_http_500_shows_status(page: Page, base_url: str) -> None:
    page.route("**/api/ask-stream", lambda r: r.fulfill(status=500, body="oops"))
    page.goto(base_url)
    ask(page, "아무 질문")
    page.wait_for_selector('#result[data-state="error"]', timeout=15000)
    assert "(500)" in page.locator("#error").inner_text()
