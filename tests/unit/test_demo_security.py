import asyncio
import calendar
import json
import re
from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.demo.guard import TokenSigner
from app.demo.install import install_demo
from app.demo.quota import DemoQuota
from app.demo.security import BodyLimitMiddleware, is_exposed

BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) demo-check"
CURL_UA = "curl/8"
C17_KEYS = {
    "bucket", "contact", "demo_mode", "limits", "notice", "privacy_notice",
    "remaining", "reset_at", "token", "token_expires_in",
}
T0 = float(calendar.timegm((2026, 10, 28, 12, 0, 30)))


class FakeClock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def make_app(**overrides: Any) -> FastAPI:
    values: dict[str, Any] = {
        "demo_mode": True,
        "demo_contact": "demo@example.com",
        "demo_rate_per_minute": 600,
    }
    values.update(overrides)
    settings = Settings(_env_file=None, **values)  # type: ignore[call-arg]
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/studio")
    def studio() -> dict[str, str]:
        return {"page": "studio"}

    @app.get("/api/options")
    def options() -> dict[str, str]:
        return {"ok": "options"}

    @app.get("/api/agents/{agent_id}")
    def get_agent(agent_id: str) -> dict[str, str]:
        if agent_id == "deny":
            raise HTTPException(status_code=403, detail={"code": "x", "message": "x"})
        return {"id": agent_id}

    @app.post("/api/agents")
    async def create_agent(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    @app.post("/api/agents/{agent_id}/turns/stream")
    async def turn(agent_id: str, request: Request) -> dict[str, Any]:
        return {"reached": True, "size": len(await request.body())}

    @app.post("/api/agents/{agent_id}/turns/audio-stream")
    async def audio(agent_id: str, request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    @app.post("/api/ask")
    def ask() -> dict[str, str]:
        return {"answer": "x"}

    @app.get("/cors")
    def cors() -> Any:
        from fastapi.responses import JSONResponse

        return JSONResponse({"ok": True}, headers={"Access-Control-Allow-Origin": "*"})

    install_demo(app, settings)
    return app


def client(app: FastAPI, peer: str = "peer-a", **kw: Any) -> TestClient:
    return TestClient(app, client=(peer, 50000), headers={"User-Agent": BROWSER_UA}, **kw)


def token_of(c: TestClient) -> str:
    tok = c.get("/api/demo").json()["token"]
    assert isinstance(tok, str) and tok
    return tok


# ---- exposure ----

def test_outside_allowlist_is_404() -> None:
    c = client(make_app())
    for path in ("/docs", "/redoc", "/openapi.json", "/static/archive/kiosk/index.html", "/cors"):
        r = c.get(path)
        assert r.status_code == 404, path
        assert r.json() == {"detail": "Not Found"}
    assert c.post("/api/ask", json={}).status_code == 404
    assert c.options("/api/options").status_code == 404
    assert c.put("/api/agents/x", json={}).status_code == 404


def test_allowlisted_paths_pass() -> None:
    c = client(make_app())
    assert c.get("/health").status_code == 200
    assert c.head("/health").status_code == 405  # 가드 통과 후 라우터 결과 (404 아님)
    assert c.get("/studio").status_code == 200
    assert c.get("/api/options").status_code == 200
    assert c.get("/api/agents/abc").json() == {"id": "abc"}


def test_is_exposed_rules() -> None:
    assert is_exposed("GET", "/static/studio/app.js")
    assert is_exposed("HEAD", "/api/presets")
    assert is_exposed("PATCH", "/api/agents/a1/settings")
    assert is_exposed("DELETE", "/api/agents/a1")
    assert not is_exposed("GET", "/static/studio/../archive/kiosk/index.html")
    assert not is_exposed("GET", "/static/studio/")
    assert not is_exposed("POST", "/api/ask-stream")
    assert not is_exposed("DELETE", "/api/agents/a1/settings")
    assert not is_exposed("OPTIONS", "/api/agents")


# ---- security headers ----

def _assert_headers(r: Any, csp_expected: bool = True) -> None:
    if csp_expected:
        csp = r.headers["content-security-policy"]
        for part in ("default-src 'self'", "script-src 'self'", "object-src 'none'",
                     "base-uri 'none'", "frame-ancestors 'self'", "style-src 'self' 'unsafe-inline'"):
            assert part in csp
    else:
        assert "content-security-policy" not in r.headers
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    pp = r.headers["permissions-policy"]
    assert "microphone=(self)" in pp and "camera=()" in pp and "geolocation=()" in pp
    assert r.headers["cross-origin-opener-policy"] == "same-origin"
    assert "access-control-allow-origin" not in r.headers


def test_security_headers_on_page_api_and_404() -> None:
    c = client(make_app())
    for r in (
        c.get("/studio", headers={"Origin": "https://evil.example"}),
        c.get("/api/options", headers={"Origin": "https://evil.example"}),
        c.get("/docs"),
    ):
        _assert_headers(r)
        assert "strict-transport-security" not in r.headers


def test_frame_ancestors_setting() -> None:
    c = client(make_app(demo_frame_ancestors="'self' https://example.org"))
    assert "frame-ancestors 'self' https://example.org" in c.get("/studio").headers["content-security-policy"]


def test_hsts_only_on_https() -> None:
    https = client(make_app(), base_url="https://testserver")
    assert https.get("/health").headers["strict-transport-security"] == "max-age=31536000"
    plain = client(make_app())
    assert "strict-transport-security" not in plain.get("/health", headers={"X-Forwarded-Proto": "https"}).headers
    proxied = client(make_app(demo_trusted_proxy_hops=1))
    assert "strict-transport-security" in proxied.get("/health", headers={"X-Forwarded-Proto": "http, https"}).headers
    assert "strict-transport-security" not in proxied.get(
        "/health", headers={"X-Forwarded-Proto": "https, http"}
    ).headers


def test_acao_stripped_when_demo_off() -> None:
    c = client(make_app(demo_mode=False))
    r = c.get("/cors")
    assert r.status_code == 200
    _assert_headers(r, csp_expected=False)


# ---- body and rate ----

def test_oversized_json_413() -> None:
    c = client(make_app(demo_bot_guard=False))
    r = c.post("/api/agents", content=b"x" * (600 * 1024), headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert r.json()["detail"] == {"code": "payload_too_large", "message": "보낸 내용이 너무 큽니다."}


def test_chunked_body_over_limit_413() -> None:
    c = client(make_app(demo_bot_guard=False))

    def gen() -> Iterator[bytes]:
        for _ in range(10):
            yield b"x" * (64 * 1024)

    r = c.post("/api/agents", content=gen())
    assert r.status_code == 413
    assert r.json()["detail"]["code"] == "payload_too_large"


def test_audio_path_uses_audio_limit() -> None:
    c = client(make_app(demo_bot_guard=False))
    ok = c.post("/api/agents/a/turns/audio-stream", content=b"x" * (600 * 1024))
    assert ok.status_code == 200 and ok.json()["size"] == 600 * 1024
    big = c.post("/api/agents/a/turns/audio-stream", content=b"x" * (2 * 1024 * 1024 + 1))
    assert big.status_code == 413


def test_body_limit_accumulates_multiple_chunks() -> None:
    reached: list[bytes] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        body = b""
        while True:
            m = await receive()
            body += m.get("body", b"")
            if not m.get("more_body"):
                break
        reached.append(body)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    def run(chunks: list[bytes]) -> list[dict[str, Any]]:
        mw = BodyLimitMiddleware(inner, max_json_bytes=100, max_audio_bytes=1000)
        msgs = [
            {"type": "http.request", "body": ch, "more_body": i < len(chunks) - 1}
            for i, ch in enumerate(chunks)
        ]
        sent: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            return msgs.pop(0) if msgs else {"type": "http.disconnect"}

        async def send(m: dict[str, Any]) -> None:
            sent.append(m)

        scope = {"type": "http", "method": "POST", "path": "/api/agents", "headers": []}
        asyncio.run(mw(scope, receive, send))
        return sent

    sent = run([b"a" * 60, b"b" * 60])
    assert sent[0]["status"] == 413 and not reached
    assert json.loads(sent[1]["body"])["detail"]["code"] == "payload_too_large"
    sent = run([b"a" * 40, b"b" * 40])
    assert sent[0]["status"] == 200 and reached == [b"a" * 40 + b"b" * 40]


def test_non_ascii_content_length_no_error() -> None:
    async def inner(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = BodyLimitMiddleware(inner, max_json_bytes=100, max_audio_bytes=1000)
    msgs = [{"type": "http.request", "body": b"x" * 200, "more_body": False}]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return msgs.pop(0) if msgs else {"type": "http.disconnect"}

    async def send(m: dict[str, Any]) -> None:
        sent.append(m)

    scope = {"type": "http", "method": "POST", "path": "/api/agents",
             "headers": [(b"content-length", "\u00b2".encode("latin-1"))]}
    asyncio.run(mw(scope, receive, send))
    assert sent[0]["status"] == 413


def test_unhandled_exception_500_has_security_headers() -> None:
    app = make_app()

    @app.get("/api/presets")
    def boom() -> None:
        raise RuntimeError("secret detail")

    r = client(app).get("/api/presets")
    assert r.status_code == 500
    assert r.json() == {"detail": {"code": "internal_error", "message": "서버 오류가 발생했습니다."}}
    assert "secret detail" not in r.text
    _assert_headers(r)


def test_rate_limit_sixth_request_429() -> None:
    app = make_app(demo_rate_per_minute=5)
    app.state.demo_quota = DemoQuota(
        app.state.demo_quota.limits, {"turns": 9, "audio_seconds": 9, "agents": 9, "scorecards": 9},
        5, clock=FakeClock(T0),
    )
    c = client(app)
    codes = [c.get("/api/options").status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]
    r = c.get("/api/options")
    assert r.json()["detail"] == {"code": "rate_limited", "message": "요청이 너무 잦습니다. 잠시 뒤 다시 시도해 주세요."}
    assert c.get("/health").status_code == 200  # /api/ 밖은 창에 포함되지 않음


# ---- bot guard ----

def test_script_ua_on_cost_endpoint_403() -> None:
    c = client(make_app())
    r = c.post("/api/agents", json={}, headers={"User-Agent": CURL_UA})
    assert r.status_code == 403
    assert r.json()["detail"] == {"code": "automated_client", "message": "브라우저에서 이용해 주세요."}
    r = c.post("/api/agents", json={}, headers={"User-Agent": ""})
    assert r.json()["detail"]["code"] == "automated_client"


def test_browser_without_token_403() -> None:
    c = client(make_app())
    r = c.post("/api/agents/a/turns/stream", json={})
    assert r.status_code == 403
    assert r.json()["detail"] == {
        "code": "demo_token_required", "message": "페이지를 새로 고친 뒤 다시 시도해 주세요."
    }


def test_token_and_browser_reach_handler() -> None:
    c = client(make_app())
    tok = token_of(c)
    r = c.post("/api/agents/a/turns/stream", json={"q": 1}, headers={"X-Demo-Token": tok})
    assert r.status_code == 200 and r.json()["reached"] is True


def test_token_bound_to_bucket() -> None:
    app = make_app()
    tok = token_of(client(app, peer="peer-a"))
    r = client(app, peer="peer-b").post("/api/agents", json={}, headers={"X-Demo-Token": tok})
    assert r.json()["detail"]["code"] == "demo_token_required"


def test_expired_token_rejected() -> None:
    app = make_app()
    clock = FakeClock(T0)
    app.state.demo_signer = TokenSigner("s", 1800, clock=clock)
    c = client(app)
    tok = token_of(c)
    clock.t = T0 + 1801
    r = c.post("/api/agents", json={}, headers={"X-Demo-Token": tok})
    assert r.json()["detail"]["code"] == "demo_token_required"


def test_curl_health_and_demo_info_open() -> None:
    c = client(make_app())
    assert c.get("/health", headers={"User-Agent": CURL_UA}).status_code == 200
    r = c.get("/api/demo", headers={"User-Agent": CURL_UA})
    assert r.status_code == 200 and r.json()["demo_mode"] is True


def test_repeated_violations_block_and_other_peer_unaffected() -> None:
    app = make_app(demo_abuse_threshold=3)
    c = client(app)
    for _ in range(3):
        assert c.post("/api/agents", json={}).status_code == 403
    r = c.get("/api/options")
    assert r.status_code == 429
    detail = r.json()["detail"]
    assert detail["code"] == "temporarily_blocked"
    assert detail["message"] == (
        "비정상적인 요청이 반복되어 잠시 이용이 제한되었습니다. 나중에 다시 시도해 주세요."
    )
    assert 1 <= detail["retry_after"] <= 600
    assert int(r.headers["retry-after"]) == detail["retry_after"]
    assert c.get("/health").status_code == 200  # /api/ 밖은 차단하지 않음
    other = client(app, peer="peer-b")
    assert other.get("/api/options").status_code == 200
    assert other.get("/api/demo").status_code == 200


def test_handler_403_counts_as_violation() -> None:
    app = make_app(demo_abuse_threshold=2)
    c = client(app)
    assert c.get("/api/agents/deny").status_code == 403
    assert c.get("/api/agents/deny").status_code == 403
    assert c.get("/api/options").json()["detail"]["code"] == "temporarily_blocked"


def test_rate_429_counts_as_violation() -> None:
    app = make_app(demo_rate_per_minute=1, demo_abuse_threshold=2)
    app.state.demo_quota = DemoQuota(
        app.state.demo_quota.limits, {"turns": 9, "audio_seconds": 9, "agents": 9, "scorecards": 9},
        1, clock=FakeClock(T0),
    )
    c = client(app)
    assert c.get("/api/options").status_code == 200
    assert c.get("/api/options").json()["detail"]["code"] == "rate_limited"
    assert c.get("/api/options").json()["detail"]["code"] == "rate_limited"
    assert c.get("/api/options").json()["detail"]["code"] == "temporarily_blocked"


def test_bot_guard_off() -> None:
    app = make_app(demo_bot_guard=False)
    assert app.state.demo_signer is None and app.state.demo_abuse is None
    c = client(app)
    r = c.post("/api/agents", json={}, headers={"User-Agent": CURL_UA})
    assert r.status_code == 200
    body = c.get("/api/demo").json()
    assert body["token"] is None and body["token_expires_in"] is None


# ---- /api/demo ----

def test_demo_info_keys_and_values() -> None:
    c = client(make_app())
    body = c.get("/api/demo").json()
    assert set(body) == C17_KEYS
    assert body["demo_mode"] is True
    assert body["contact"] == "demo@example.com"
    assert set(body["limits"]) == {"turns", "audio_seconds", "agents", "scorecards"}
    assert body["remaining"]["turns"] == body["limits"]["turns"]
    assert re.fullmatch(r"[0-9a-f]{16}", body["bucket"])
    assert body["token_expires_in"] == 1800
    assert re.fullmatch(r"\d+\.[0-9a-f]{32}", body["token"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T00:00:00Z", body["reset_at"])
    assert body["notice"].startswith("데모 버전입니다")
    assert "외부 AI API로 전송됩니다" in body["privacy_notice"]


def test_demo_info_does_not_charge() -> None:
    app = make_app()
    c = client(app)
    before = c.get("/api/demo").json()["remaining"]
    for _ in range(3):
        c.get("/api/demo")
    assert c.get("/api/demo").json()["remaining"] == before


# ---- demo off ----

def test_demo_off_no_restrictions() -> None:
    app = make_app(demo_mode=False, demo_contact="")
    assert app.state.demo_quota is None and app.state.demo_signer is None and app.state.demo_abuse is None
    c = client(app)
    body = c.get("/api/demo").json()
    assert set(body) == C17_KEYS
    assert body["demo_mode"] is False and body["contact"] is None
    for k in ("limits", "remaining", "reset_at", "bucket", "token", "token_expires_in"):
        assert body[k] is None
    assert body["privacy_notice"].startswith("질문 문장은")
    assert c.get("/docs").status_code == 200
    assert c.post("/api/ask", json={}).status_code == 200
    assert c.post("/api/agents", json={}, headers={"User-Agent": CURL_UA}).status_code == 200
    big = c.post("/api/agents", content=b"x" * (600 * 1024))
    assert big.status_code == 200 and big.json()["size"] == 600 * 1024
    assert all(c.get("/api/options").status_code == 200 for _ in range(40))
    _assert_headers(c.get("/studio"), csp_expected=False)


def test_demo_off_no_csp_other_headers_kept() -> None:
    app = make_app(demo_mode=False)

    @app.get("/static/archive/kiosk/index.html")
    def kiosk() -> dict[str, str]:
        return {"page": "kiosk"}

    c = client(app)
    r = c.get("/static/archive/kiosk/index.html")
    assert r.status_code == 200
    _assert_headers(r, csp_expected=False)
    https = client(make_app(demo_mode=False), base_url="https://testserver")
    h = https.get("/health")
    assert "content-security-policy" not in h.headers
    assert h.headers["strict-transport-security"] == "max-age=31536000"


def test_demo_on_has_csp_on_kiosk_404() -> None:
    _assert_headers(client(make_app()).get("/static/archive/kiosk/index.html"))
