import calendar

import pytest

from app.demo import guard
from app.demo.guard import AbuseTracker, TokenSigner, is_cost_request, is_script_ua, parse_steps


class FakeClock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


T0 = float(calendar.timegm((2026, 10, 28, 12, 0, 0)))
CHROME = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
HEADLESS = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/130.0"
SCRIPT_UAS = [
    "curl/8.4.0", "Wget/1.21", "python-requests/2.31", "python-httpx/0.27", "Python-urllib/3.11",
    "aiohttp/3.9", "Go-http-client/1.1", "okhttp/4.12", "Java/17.0.2", "libwww-perl/6.72",
    "node-fetch/1.0", "axios/1.6.0", "Scrapy/2.11", "HTTPie/3.2", "PostmanRuntime/7.36",
]


# ---- TokenSigner ----

def test_issued_token_verifies() -> None:
    clock = FakeClock(T0)
    s = TokenSigner("secret", 1800, clock=clock)
    token = s.issue("bucketA")
    exp, sig = token.split(".")
    assert int(exp) == int(T0) + 1800 and len(sig) == 32
    assert s.verify("bucketA", token) is True


def test_other_bucket_rejected() -> None:
    s = TokenSigner("secret", 1800, clock=FakeClock(T0))
    assert s.verify("bucketB", s.issue("bucketA")) is False


def test_expired_token_rejected() -> None:
    clock = FakeClock(T0)
    s = TokenSigner("secret", 1800, clock=clock)
    token = s.issue("b")
    clock.t = T0 + 1801
    assert s.verify("b", token) is False


_EXP = str(int(T0) + 100)  # 만료·미래 검사를 통과하는 exp — 서명 형식 검사만 남긴다


@pytest.mark.parametrize("sig", [
    "\u00e9" * 32,  # 비ASCII
    "0" * 31,
    "0" * 33,
    "0123456789ABCDEF0123456789abcdef",  # 대문자
    "0123456789abcdeg0123456789abcdef",  # 비hex
    "\u0660" * 32,  # 비ASCII 숫자
])
def test_malformed_signature_rejected(sig: str) -> None:
    s = TokenSigner("secret", 1800, clock=FakeClock(T0))
    assert s.verify("b", f"{_EXP}.{sig}") is False


def test_far_future_exp_rejected() -> None:
    clock = FakeClock(T0)
    future = TokenSigner("secret", 1800, clock=FakeClock(T0 + 1000))
    token = future.issue("b")  # exp = now + 2800 > now + 1800 + 60, 서명은 올바름
    assert TokenSigner("secret", 1800, clock=clock).verify("b", token) is False
    near = TokenSigner("secret", 1800, clock=FakeClock(T0 + 60)).issue("b")
    assert TokenSigner("secret", 1800, clock=clock).verify("b", near) is True


@pytest.mark.parametrize("token", ["", "abc", "1.2.3", None, "x.0123456789abcdef0123456789abcdef",
                                   "\u00b2.0123456789abcdef0123456789abcdef"])
def test_malformed_token_rejected(token: str | None) -> None:
    s = TokenSigner("secret", 1800, clock=FakeClock(T0))
    assert s.verify("b", token) is False


def test_tampered_signature_rejected() -> None:
    s = TokenSigner("secret", 1800, clock=FakeClock(T0))
    exp, sig = s.issue("b").split(".")
    bad = ("0" if sig[0] != "0" else "1") + sig[1:]
    assert s.verify("b", f"{exp}.{bad}") is False


def test_empty_secret_random_per_instance() -> None:
    a = TokenSigner("", 1800, clock=FakeClock(T0))
    b = TokenSigner("", 1800, clock=FakeClock(T0))
    assert a.verify("b", a.issue("b")) is True
    assert b.verify("b", a.issue("b")) is False
    assert a.verify("b", b.issue("b")) is False
    assert a.ttl_s == 1800


# ---- UA ----

@pytest.mark.parametrize("ua", SCRIPT_UAS)
def test_script_ua_detected(ua: str) -> None:
    assert is_script_ua(ua) is True
    assert is_script_ua(ua.upper()) is True


@pytest.mark.parametrize("ua", [None, "", "   "])
def test_empty_ua_is_script(ua: str | None) -> None:
    assert is_script_ua(ua) is True


@pytest.mark.parametrize("ua", [CHROME, HEADLESS])
def test_browser_ua_allowed(ua: str) -> None:
    assert is_script_ua(ua) is False


# ---- cost routes ----

@pytest.mark.parametrize("path", [
    "/api/agents",
    "/api/agents/a_1/turns/stream",
    "/api/agents/a_1/turns/audio-stream",
    "/api/agents/a_1/compare",
    "/api/agents/a_1/scorecards",
])
def test_cost_paths(path: str) -> None:
    assert is_cost_request("POST", path) is True
    assert is_cost_request("GET", path) is False
    assert is_cost_request("PATCH", path) is False


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/demo"),
    ("POST", "/api/demo"),
    ("POST", "/api/agents/a_1"),
    ("POST", "/api/agents/a_1/turns/stream/x"),
    ("POST", "/api/agents/a/b/compare"),
    ("GET", "/health"),
])
def test_non_cost_paths(method: str, path: str) -> None:
    assert is_cost_request(method, path) is False


def test_cost_routes_count() -> None:
    assert len(guard.COST_ROUTES) == 5


# ---- parse_steps ----

def test_parse_steps_ok() -> None:
    assert parse_steps("600,3600,86400") == (600, 3600, 86400)
    assert parse_steps(" 10 , 20 ") == (10, 20)


@pytest.mark.parametrize("raw", ["", "600,0", "600,abc", "600,-5", "600,,3600"])
def test_parse_steps_errors(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_steps(raw)


# ---- AbuseTracker ----

def _tracker(clock: FakeClock) -> AbuseTracker:
    return AbuseTracker(threshold=3, window_s=300, steps=(600, 3600, 86400), clock=clock)


def _hit(t: AbuseTracker, bucket: str, n: int) -> None:
    for _ in range(n):
        t.record(bucket)


def test_not_blocked_initially_and_below_threshold() -> None:
    clock = FakeClock(T0)
    t = _tracker(clock)
    assert t.blocked_for("a") == 0
    _hit(t, "a", 2)
    assert t.blocked_for("a") == 0


def test_escalating_blocks() -> None:
    clock = FakeClock(T0)
    t = _tracker(clock)
    _hit(t, "a", 3)
    first = t.blocked_for("a")
    assert 1 <= first <= 600
    assert t.blocked_for("b") == 0
    clock.t += 601
    assert t.blocked_for("a") == 0
    _hit(t, "a", 3)
    second = t.blocked_for("a")
    assert 600 < second <= 3600
    clock.t += 3601
    _hit(t, "a", 3)
    third = t.blocked_for("a")
    assert 3600 < third <= 86400


def test_last_step_repeats() -> None:
    clock = FakeClock(T0)
    t = AbuseTracker(threshold=1, window_s=300, steps=(10, 20), clock=clock)
    for expected in (10, 20, 20):
        t.record("a")
        assert t.blocked_for("a") == expected
        clock.t += expected + 1


def test_blocked_for_rounds_up() -> None:
    clock = FakeClock(T0)
    t = _tracker(clock)
    _hit(t, "a", 3)
    clock.t += 0.5
    assert t.blocked_for("a") == 600


def test_window_drops_old_violations() -> None:
    clock = FakeClock(T0)
    t = _tracker(clock)
    _hit(t, "a", 2)
    clock.t += 301
    t.record("a")
    assert t.blocked_for("a") == 0
    _hit(t, "a", 2)
    assert t.blocked_for("a") > 0


def test_level_resets_on_new_utc_day() -> None:
    clock = FakeClock(float(calendar.timegm((2026, 10, 28, 23, 0, 0))))
    t = _tracker(clock)
    _hit(t, "a", 3)
    clock.t += 601
    _hit(t, "a", 3)
    assert t.blocked_for("a") > 600  # level 1 → 3600
    clock.t = float(calendar.timegm((2026, 10, 29, 2, 0, 0)))  # 다음 UTC 날, 차단 만료 후
    assert t.blocked_for("a") == 0
    _hit(t, "a", 3)
    assert 1 <= t.blocked_for("a") <= 600


def test_bucket_cap_evicts_oldest_unblocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "MAX_BUCKETS", 3)
    clock = FakeClock(T0)
    t = _tracker(clock)
    _hit(t, "blocked", 3)  # 가장 오래됐지만 차단 중
    t.record("old")
    t.record("mid")
    t.record("new")  # 상한 → 차단 중 아닌 가장 오래된 "old" 를 버린다
    assert t.blocked_for("blocked") > 0
    assert set(t._entries) == {"blocked", "mid", "new"}
