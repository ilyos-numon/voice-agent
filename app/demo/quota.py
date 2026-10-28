"""방문자별·전역 일일 한도와 분당 요청 창 (인메모리, UTC 날짜 기준)."""

from __future__ import annotations

import hashlib
import ipaddress
import secrets
import threading
import time
from collections.abc import Callable
from typing import Literal

from fastapi import HTTPException, Request
from starlette.types import Scope

Kind = Literal["turns", "audio_seconds", "agents", "scorecards"]
KINDS: tuple[Kind, ...] = ("turns", "audio_seconds", "agents", "scorecards")

_QUOTA_MESSAGE = "오늘 데모 사용 한도를 다 썼습니다. 내일 다시 이용해 주세요."
_CAP_MESSAGE = "오늘 데모 전체 사용량이 모두 소진되었습니다. 내일 다시 이용해 주세요."


class QuotaExceeded(Exception):
    def __init__(self, kind: Kind, reset_at: str) -> None:
        super().__init__(kind)
        self.kind: Kind = kind
        self.reset_at = reset_at


class DailyCapReached(Exception):
    def __init__(self, kind: Kind, reset_at: str) -> None:
        super().__init__(kind)
        self.kind: Kind = kind
        self.reset_at = reset_at


class RateLimited(Exception): ...


def client_ip(scope_client_host: str | None, xff: str | None, trusted_hops: int) -> str:
    peer = scope_client_host or "unknown"
    if trusted_hops <= 0 or not xff:
        return peer
    parts = [p.strip() for p in xff.split(",")]
    parts = [p for p in parts if p]
    if len(parts) < trusted_hops:
        return peer
    return parts[-trusted_hops]


def normalize_ip(ip: str) -> str:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(addr, ipaddress.IPv6Address):
        return str(ipaddress.IPv6Network(f"{addr}/64", strict=False))
    return ip


def utc_day(ts: float) -> tuple[int, int]:
    t = time.gmtime(ts)
    return (t.tm_year, t.tm_yday)


def _next_utc_midnight(ts: float) -> str:
    start = int(ts) - int(ts) % 86400
    return time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(start + 86400))


class DemoQuota:
    def __init__(
        self,
        limits: dict[Kind, int],
        global_caps: dict[Kind, int],
        rate_per_minute: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.limits: dict[Kind, int] = dict(limits)
        self._caps: dict[Kind, int] = dict(global_caps)
        self._rate = rate_per_minute
        self._clock = clock
        self._salt = secrets.token_hex(16)
        self._lock = threading.Lock()
        self._day: tuple[int, int] = utc_day(clock())
        self._visitors: dict[str, dict[Kind, int]] = {}
        self._totals: dict[Kind, int] = dict.fromkeys(KINDS, 0)
        self._windows: dict[str, tuple[int, int]] = {}

    def bucket(self, ip: str) -> str:
        raw = (self._salt + normalize_ip(ip)).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def bucket_for_scope(self, scope: Scope, trusted_hops: int) -> str:
        client = scope.get("client")
        host = client[0] if client else None
        xff: str | None = None
        for name, value in scope.get("headers") or []:
            if name.lower() == b"x-forwarded-for":
                xff = value.decode("latin-1")
                break
        return self.bucket(client_ip(host, xff, trusted_hops))

    def _roll_locked(self) -> None:
        day = utc_day(self._clock())
        if day != self._day:
            self._day = day
            self._visitors.clear()
            self._totals = dict.fromkeys(KINDS, 0)

    def charge(self, bucket: str, kind: Kind, amount: int = 1) -> None:
        with self._lock:
            self._roll_locked()
            if self._totals[kind] + amount > self._caps[kind]:
                raise DailyCapReached(kind, self.reset_at())
            used = self._visitors.get(bucket, {}).get(kind, 0)
            if used + amount > self.limits[kind]:
                raise QuotaExceeded(kind, self.reset_at())
            self._totals[kind] += amount
            self._visitors.setdefault(bucket, dict.fromkeys(KINDS, 0))[kind] = used + amount

    def refund(self, bucket: str, kind: Kind, amount: int = 1) -> None:
        with self._lock:
            if utc_day(self._clock()) != self._day:
                return
            counters = self._visitors.get(bucket)
            if counters is None:
                return
            back = min(amount, counters[kind])
            if back <= 0:
                return
            counters[kind] -= back
            self._totals[kind] = max(0, self._totals[kind] - back)

    def remaining(self, bucket: str) -> dict[Kind, int]:
        with self._lock:
            self._roll_locked()
            counters = self._visitors.get(bucket, {})
            return {k: max(0, self.limits[k] - counters.get(k, 0)) for k in KINDS}

    def reset_at(self) -> str:
        return _next_utc_midnight(self._clock())

    def hit_rate(self, bucket: str) -> None:
        with self._lock:
            window = int(self._clock() // 60)
            for b in [b for b, (w, _) in self._windows.items() if w != window]:
                del self._windows[b]
            _, count = self._windows.get(bucket, (window, 0))
            if count >= self._rate:
                raise RateLimited(bucket)
            self._windows[bucket] = (window, count + 1)


def _quota_of(request: Request) -> DemoQuota | None:
    quota = getattr(request.app.state, "demo_quota", None)
    return quota if isinstance(quota, DemoQuota) else None


def request_bucket(request: Request) -> str | None:
    quota = _quota_of(request)
    if quota is None:
        return None
    settings = getattr(request.app.state, "demo_settings", None)
    hops = int(getattr(settings, "demo_trusted_proxy_hops", 0))
    return quota.bucket_for_scope(request.scope, hops)


def charge_request(request: Request, kind: Kind, amount: int = 1) -> None:
    quota = _quota_of(request)
    bucket = request_bucket(request)
    if quota is None or bucket is None:
        return
    try:
        quota.charge(bucket, kind, amount)
    except QuotaExceeded as e:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "demo_quota_exceeded",
                "message": _QUOTA_MESSAGE,
                "kind": e.kind,
                "reset_at": e.reset_at,
            },
        ) from e
    except DailyCapReached as e:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "demo_daily_cap",
                "message": _CAP_MESSAGE,
                "kind": e.kind,
                "reset_at": e.reset_at,
            },
        ) from e


def refund_request(request: Request, kind: Kind, amount: int = 1) -> None:
    quota = _quota_of(request)
    bucket = request_bucket(request)
    if quota is None or bucket is None:
        return
    quota.refund(bucket, kind, amount)
