"""봇 대응 코어: 비용 경로 판별·스크립트 UA·요청 토큰·단계별 임시 차단 (인메모리)."""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.demo.quota import utc_day

COST_ROUTES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/api/agents$"),
    re.compile(r"^/api/agents/[^/]+/turns/stream$"),
    re.compile(r"^/api/agents/[^/]+/turns/audio-stream$"),
    re.compile(r"^/api/agents/[^/]+/compare$"),
    re.compile(r"^/api/agents/[^/]+/scorecards$"),
)

SCRIPT_UA: re.Pattern[str] = re.compile(
    r"curl/|wget/|python-requests|python-httpx|python-urllib|aiohttp|go-http-client|okhttp"
    r"|java/|libwww-perl|node-fetch|axios/|scrapy|httpie|postmanruntime",
    re.IGNORECASE,
)

MAX_BUCKETS = 10000
_FUTURE_SLACK_S = 60
_SIG_RE = re.compile(r"[0-9a-f]{32}")
_EXP_RE = re.compile(r"[0-9]{1,12}")


def is_cost_request(method: str, path: str) -> bool:
    if method.upper() != "POST":
        return False
    return any(p.match(path) for p in COST_ROUTES)


def is_script_ua(ua: str | None) -> bool:
    if ua is None or not ua.strip():
        return True
    return SCRIPT_UA.search(ua) is not None


class TokenSigner:
    def __init__(self, secret: str, ttl_s: int, clock: Callable[[], float] = time.time) -> None:
        self._key = secret.encode("utf-8") if secret else secrets.token_bytes(32)
        self.ttl_s = ttl_s
        self._clock = clock

    def _sign(self, bucket: str, exp: int) -> str:
        msg = f"{bucket}.{exp}".encode()
        return hmac.new(self._key, msg, hashlib.sha256).hexdigest()[:32]

    def issue(self, bucket: str) -> str:
        exp = int(self._clock()) + self.ttl_s
        return f"{exp}.{self._sign(bucket, exp)}"

    def verify(self, bucket: str, token: str | None) -> bool:
        if not token:
            return False
        parts = token.split(".")
        if len(parts) != 2 or not _EXP_RE.fullmatch(parts[0]) or not _SIG_RE.fullmatch(parts[1]):
            return False
        exp = int(parts[0])
        now = self._clock()
        if exp <= now or exp > now + self.ttl_s + _FUTURE_SLACK_S:
            return False
        return hmac.compare_digest(self._sign(bucket, exp), parts[1])


def parse_steps(raw: str) -> tuple[int, ...]:
    items = [p.strip() for p in raw.split(",")]
    if not raw.strip() or any(not p for p in items):
        raise ValueError(f"invalid block steps: {raw!r}")
    try:
        steps = tuple(int(p) for p in items)
    except ValueError as e:
        raise ValueError(f"invalid block steps: {raw!r}") from e
    if any(s <= 0 for s in steps):
        raise ValueError(f"invalid block steps: {raw!r}")
    return steps


@dataclass
class _Entry:
    hits: list[float] = field(default_factory=list)
    level: int = 0
    blocked_until: float = 0.0


class AbuseTracker:
    def __init__(
        self,
        threshold: int,
        window_s: int,
        steps: tuple[int, ...],
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not steps:
            raise ValueError("steps must not be empty")
        self._threshold = threshold
        self._window = window_s
        self._steps = steps
        self._clock = clock
        self._lock = threading.Lock()
        self._day: tuple[int, int] = utc_day(clock())
        self._entries: dict[str, _Entry] = {}

    def _roll_locked(self, now: float) -> None:
        day = utc_day(now)
        if day != self._day:
            self._day = day
            for entry in self._entries.values():
                entry.level = 0

    def blocked_for(self, bucket: str) -> int:
        with self._lock:
            now = self._clock()
            self._roll_locked(now)
            entry = self._entries.get(bucket)
            if entry is None or entry.blocked_until <= now:
                return 0
            return math.ceil(entry.blocked_until - now)

    def _evict_locked(self, now: float) -> None:
        while len(self._entries) >= MAX_BUCKETS:
            victim = next((b for b, e in self._entries.items() if e.blocked_until <= now), None)
            if victim is None:
                victim = next(iter(self._entries))
            del self._entries[victim]

    def record(self, bucket: str) -> None:
        with self._lock:
            now = self._clock()
            self._roll_locked(now)
            entry = self._entries.pop(bucket, None)
            if entry is None:
                self._evict_locked(now)
                entry = _Entry()
            self._entries[bucket] = entry  # 최근 기록 순서로 다시 넣는다
            entry.hits = [t for t in entry.hits if t > now - self._window]
            entry.hits.append(now)
            if len(entry.hits) >= self._threshold:
                entry.blocked_until = now + self._steps[min(entry.level, len(self._steps) - 1)]
                entry.level += 1
                entry.hits = []
