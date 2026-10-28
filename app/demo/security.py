"""데모 미들웨어 (순수 ASGI): 보안 헤더·노출 화이트리스트·봇 가드·분당 창·본문 크기."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.demo.guard import AbuseTracker, TokenSigner, is_cost_request, is_script_ua
from app.demo.quota import DemoQuota, RateLimited

CSP_TEMPLATE = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; media-src 'self' blob: data:; connect-src 'self'; "
    "font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors {frame_ancestors}"
)
PERMISSIONS_POLICY = "microphone=(self), camera=(), geolocation=()"
HSTS_VALUE = "max-age=31536000"

log = logging.getLogger(__name__)
_DIGITS_RE = re.compile(r"[0-9]+")

MSG_RATE_LIMITED = "요청이 너무 잦습니다. 잠시 뒤 다시 시도해 주세요."
MSG_PAYLOAD_TOO_LARGE = "보낸 내용이 너무 큽니다."
MSG_TOKEN_REQUIRED = "페이지를 새로 고친 뒤 다시 시도해 주세요."
MSG_AUTOMATED_CLIENT = "브라우저에서 이용해 주세요."
MSG_INTERNAL_ERROR = "서버 오류가 발생했습니다."
MSG_TEMPORARILY_BLOCKED = (
    "비정상적인 요청이 반복되어 잠시 이용이 제한되었습니다. 나중에 다시 시도해 주세요."
)

_GET = frozenset({"GET", "HEAD"})
_POST = frozenset({"POST"})
_ID = r"[^/]+"

ALLOWLIST: list[tuple[frozenset[str], re.Pattern[str]]] = [
    (_GET, re.compile(r"^/health$")),
    (_GET, re.compile(r"^/$")),
    (_GET, re.compile(r"^/talk$")),
    (_GET, re.compile(r"^/studio$")),
    (_GET, re.compile(r"^/studio/app$")),
    (_GET, re.compile(r"^/static/studio/.+$")),
    (_GET, re.compile(r"^/api/demo$")),
    (_GET, re.compile(r"^/api/options$")),
    (_GET, re.compile(r"^/api/presets$")),
    (_GET, re.compile(rf"^/api/agents/{_ID}$")),
    (_GET, re.compile(rf"^/api/agents/{_ID}/chunks$")),
    (_GET, re.compile(rf"^/api/scorecards/{_ID}$")),
    (_POST, re.compile(r"^/api/agents$")),
    (_POST, re.compile(rf"^/api/agents/{_ID}/sessions$")),
    (_POST, re.compile(rf"^/api/agents/{_ID}/turns/stream$")),
    (_POST, re.compile(rf"^/api/agents/{_ID}/turns/audio-stream$")),
    (_POST, re.compile(rf"^/api/agents/{_ID}/compare$")),
    (_POST, re.compile(rf"^/api/agents/{_ID}/scorecards$")),
    (frozenset({"PATCH"}), re.compile(rf"^/api/agents/{_ID}/settings$")),
    (frozenset({"DELETE"}), re.compile(rf"^/api/agents/{_ID}$")),
]


def is_exposed(method: str, path: str) -> bool:
    """화이트리스트에 있는 메서드·경로인지. `.`·`..` 경로 조각은 항상 거절."""
    if any(seg in (".", "..") for seg in path.split("/")):
        return False
    m = method.upper()
    return any(m in methods and pattern.match(path) for methods, pattern in ALLOWLIST)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or []:
        if key.lower() == name:
            return bytes(value).decode("latin-1")
    return None


async def _send_json(
    send: Send, status: int, payload: Any, extra_headers: list[tuple[bytes, bytes]] | None = None
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("latin-1")),
    ]
    headers.extend(extra_headers or [])
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _send_error(
    send: Send,
    status: int,
    code: str,
    message: str,
    extra: dict[str, Any] | None = None,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    detail: dict[str, Any] = {"code": code, "message": message}
    detail.update(extra or {})
    await _send_json(send, status, {"detail": detail}, extra_headers)


def _state_attr(scope: Scope, name: str) -> Any:
    app = scope.get("app")
    state = getattr(app, "state", None)
    return getattr(state, name, None)


def _bucket(scope: Scope, quota: DemoQuota, trusted_hops: int) -> str:
    return quota.bucket_for_scope(scope, trusted_hops)


class SecurityHeadersMiddleware:
    """모든 응답에 보안 헤더를 붙이고 `Access-Control-Allow-Origin` 을 지운다. CSP 는 `csp=True` 일 때만."""

    def __init__(
        self, app: ASGIApp, frame_ancestors: str = "'self'", trusted_hops: int = 0, csp: bool = True
    ) -> None:
        self.app = app
        self.csp = CSP_TEMPLATE.format(frame_ancestors=frame_ancestors) if csp else None
        self.trusted_hops = trusted_hops

    def _is_https(self, scope: Scope) -> bool:
        if scope.get("scheme") == "https":
            return True
        if self.trusted_hops > 0:
            proto = _header(scope, b"x-forwarded-proto")
            if proto:
                parts = [p.strip().lower() for p in proto.split(",") if p.strip()]
                return bool(parts) and parts[-1] == "https"
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        hsts = self._is_https(scope)
        drop = {
            b"content-security-policy",
            b"x-content-type-options",
            b"referrer-policy",
            b"permissions-policy",
            b"cross-origin-opener-policy",
            b"strict-transport-security",
            b"access-control-allow-origin",
        }

        started = False

        async def wrapped(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = [(k, v) for k, v in message.get("headers") or [] if bytes(k).lower() not in drop]
                if self.csp is not None:
                    headers.append((b"content-security-policy", self.csp.encode("latin-1")))
                headers += [
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", PERMISSIONS_POLICY.encode("latin-1")),
                    (b"cross-origin-opener-policy", b"same-origin"),
                ]
                if hsts:
                    headers.append((b"strict-transport-security", HSTS_VALUE.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, wrapped)
        except Exception as e:
            if started:
                raise
            log.error("unhandled error: %s", type(e).__name__)
            await _send_error(wrapped, 500, "internal_error", MSG_INTERNAL_ERROR)


class ExposureGuardMiddleware:
    """화이트리스트 밖 요청은 라우팅 전에 404 (FastAPI 기본 본문)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if not is_exposed(scope.get("method", ""), scope.get("path", "")):
            await _send_json(send, 404, {"detail": "Not Found"})
            return
        await self.app(scope, receive, send)


class BotGuardMiddleware:
    """`/api/` 요청: 임시 차단·스크립트 UA·요청 토큰 검사, 403/413/429 응답을 위반으로 기록."""

    def __init__(self, app: ASGIApp, trusted_hops: int = 0) -> None:
        self.app = app
        self.trusted_hops = trusted_hops

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return
        abuse = _state_attr(scope, "demo_abuse")
        quota = _state_attr(scope, "demo_quota")
        if not isinstance(abuse, AbuseTracker) or not isinstance(quota, DemoQuota):
            await self.app(scope, receive, send)
            return
        bucket = _bucket(scope, quota, self.trusted_hops)
        wait = abuse.blocked_for(bucket)
        if wait > 0:
            await _send_error(
                send,
                429,
                "temporarily_blocked",
                MSG_TEMPORARILY_BLOCKED,
                {"retry_after": wait},
                [(b"retry-after", str(wait).encode("latin-1"))],
            )
            return
        method = scope.get("method", "")
        path = scope.get("path", "")
        if is_cost_request(method, path):
            if is_script_ua(_header(scope, b"user-agent")):
                abuse.record(bucket)
                await _send_error(send, 403, "automated_client", MSG_AUTOMATED_CLIENT)
                return
            signer = _state_attr(scope, "demo_signer")
            if isinstance(signer, TokenSigner) and not signer.verify(
                bucket, _header(scope, b"x-demo-token")
            ):
                abuse.record(bucket)
                await _send_error(send, 403, "demo_token_required", MSG_TOKEN_REQUIRED)
                return

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start" and message.get("status") in (403, 413, 429):
                abuse.record(bucket)
            await send(message)

        await self.app(scope, receive, wrapped)


class RateLimitMiddleware:
    """`/api/` 요청을 버킷별 고정 60초 창으로 제한."""

    def __init__(self, app: ASGIApp, trusted_hops: int = 0) -> None:
        self.app = app
        self.trusted_hops = trusted_hops

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        quota = _state_attr(scope, "demo_quota")
        if (
            scope["type"] != "http"
            or not scope.get("path", "").startswith("/api/")
            or not isinstance(quota, DemoQuota)
        ):
            await self.app(scope, receive, send)
            return
        try:
            quota.hit_rate(_bucket(scope, quota, self.trusted_hops))
        except RateLimited:
            await _send_error(send, 429, "rate_limited", MSG_RATE_LIMITED)
            return
        await self.app(scope, receive, send)


class BodyLimitMiddleware:
    """본문 크기 제한. Content-Length 와 실제 누적 크기(청크 포함)를 모두 핸들러 전에 검사."""

    def __init__(self, app: ASGIApp, max_json_bytes: int, max_audio_bytes: int) -> None:
        self.app = app
        self.max_json_bytes = max_json_bytes
        self.max_audio_bytes = max_audio_bytes

    def _limit(self, path: str) -> int:
        return self.max_audio_bytes if path.endswith("/turns/audio-stream") else self.max_json_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self._limit(scope.get("path", ""))
        declared = _header(scope, b"content-length")
        if declared is not None and _DIGITS_RE.fullmatch(declared.strip()) and int(declared) > limit:
            await _send_error(send, 413, "payload_too_large", MSG_PAYLOAD_TOO_LARGE)
            return
        buffered: list[Message] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                buffered.append(message)
                break
            total += len(message.get("body", b""))
            if total > limit:
                await _send_error(send, 413, "payload_too_large", MSG_PAYLOAD_TOO_LARGE)
                return
            buffered.append(message)
            if not message.get("more_body", False):
                break

        async def replay() -> Message:
            if buffered:
                return buffered.pop(0)
            return await receive()

        await self.app(scope, replay, send)
