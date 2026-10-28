import calendar

import pytest
from fastapi import FastAPI, HTTPException, Request

from app.config import Settings
from app.demo.quota import (
    KINDS,
    DailyCapReached,
    DemoQuota,
    Kind,
    QuotaExceeded,
    RateLimited,
    charge_request,
    client_ip,
    normalize_ip,
    refund_request,
    request_bucket,
    utc_day,
)


class FakeClock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


DAY1_NOON = float(calendar.timegm((2026, 10, 28, 12, 0, 0)))
DAY1_LAST = float(calendar.timegm((2026, 10, 28, 23, 59, 59)))
DAY2_START = float(calendar.timegm((2026, 10, 29, 0, 0, 0)))

LIMITS: dict[Kind, int] = {"turns": 3, "audio_seconds": 20, "agents": 2, "scorecards": 1}
CAPS: dict[Kind, int] = {"turns": 100, "audio_seconds": 100, "agents": 100, "scorecards": 100}


def make(
    clock: FakeClock | None = None,
    limits: dict[Kind, int] | None = None,
    caps: dict[Kind, int] | None = None,
    rate: int = 30,
) -> DemoQuota:
    return DemoQuota(
        limits or LIMITS,
        caps or CAPS,
        rate,
        clock=clock or FakeClock(DAY1_NOON),
    )


def test_settings_defaults() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.demo_mode is False
    assert s.demo_contact == ""
    assert s.demo_daily_turns == 10
    assert s.demo_daily_audio_seconds == 200
    assert s.demo_daily_agents == 2
    assert s.demo_daily_scorecards == 2
    assert s.demo_global_daily_turns == 500
    assert s.demo_global_daily_audio_seconds == 2000
    assert s.demo_global_daily_agents == 100
    assert s.demo_global_daily_scorecards == 30
    assert s.demo_rate_per_minute == 30
    assert s.demo_max_json_bytes == 524288
    assert s.demo_max_audio_bytes == 2097152
    assert s.demo_max_audio_seconds_per_turn == 20
    assert s.demo_trusted_proxy_hops == 0
    assert s.demo_frame_ancestors == "'self'"
    assert s.demo_bot_guard is True
    assert s.demo_token_secret == ""
    assert s.demo_token_ttl_s == 1800
    assert s.demo_abuse_threshold == 10
    assert s.demo_abuse_window_s == 300
    assert s.demo_block_steps == "600,3600,86400"
    assert s.demo_llm_daily_calls == 500
    assert s.agent_summary_default is False


def test_kinds() -> None:
    assert KINDS == ("turns", "audio_seconds", "agents", "scorecards")


def test_quota_exhausted_then_rejected() -> None:
    q = make()
    b = q.bucket("peer-x")
    for _ in range(3):
        q.charge(b, "turns")
    assert q.remaining(b)["turns"] == 0
    with pytest.raises(QuotaExceeded) as ei:
        q.charge(b, "turns")
    assert ei.value.kind == "turns"
    assert ei.value.reset_at == "2026-10-29T00:00:00Z"
    assert q.remaining(b)["turns"] == 0


def test_charge_amount_over_remaining_rejected_without_change() -> None:
    q = make()
    b = q.bucket("peer-a")
    q.charge(b, "turns", 2)
    with pytest.raises(QuotaExceeded):
        q.charge(b, "turns", 2)
    assert q.remaining(b)["turns"] == 1


def test_remaining_starts_at_limits() -> None:
    q = make()
    assert q.remaining(q.bucket("peer-a")) == LIMITS
    assert q.limits == LIMITS


def test_refund_restores_and_floors_at_zero() -> None:
    q = make()
    b = q.bucket("peer-a")
    q.charge(b, "turns", 2)
    q.refund(b, "turns")
    assert q.remaining(b)["turns"] == 2
    q.refund(b, "turns", 5)
    assert q.remaining(b)["turns"] == 3
    q.refund(q.bucket("never-charged"), "turns")
    assert q.remaining(q.bucket("never-charged"))["turns"] == 3


def test_refund_releases_global_total() -> None:
    caps: dict[Kind, int] = {**CAPS, "turns": 1}
    q = make(caps=caps)
    a, b = q.bucket("peer-a"), q.bucket("peer-b")
    q.charge(a, "turns")
    q.refund(a, "turns")
    q.charge(b, "turns")


def test_global_cap_reached_regardless_of_visitor_quota() -> None:
    caps: dict[Kind, int] = {**CAPS, "turns": 2}
    q = make(caps=caps)
    q.charge(q.bucket("peer-a"), "turns")
    q.charge(q.bucket("peer-b"), "turns")
    c = q.bucket("peer-c")
    with pytest.raises(DailyCapReached) as ei:
        q.charge(c, "turns")
    assert ei.value.kind == "turns"
    assert ei.value.reset_at == "2026-10-29T00:00:00Z"
    assert q.remaining(c)["turns"] == 3


def test_global_checked_before_visitor() -> None:
    caps: dict[Kind, int] = {**CAPS, "turns": 3}
    q = make(caps=caps)
    b = q.bucket("peer-a")
    for _ in range(3):
        q.charge(b, "turns")
    with pytest.raises(DailyCapReached):
        q.charge(b, "turns")


def test_visitor_rejection_does_not_increase_global() -> None:
    caps: dict[Kind, int] = {**CAPS, "scorecards": 2}
    q = make(caps=caps)
    a = q.bucket("peer-a")
    q.charge(a, "scorecards")
    with pytest.raises(QuotaExceeded):
        q.charge(a, "scorecards")
    q.charge(q.bucket("peer-b"), "scorecards")


def test_utc_day_rollover_resets_counters() -> None:
    clock = FakeClock(DAY1_LAST)
    q = make(clock=clock)
    b = q.bucket("peer-a")
    for _ in range(3):
        q.charge(b, "turns")
    clock.t = DAY2_START
    assert q.remaining(b)["turns"] == 3
    assert q.reset_at() == "2026-10-30T00:00:00Z"
    q.charge(b, "turns")


def test_refund_after_day_change_ignored() -> None:
    clock = FakeClock(DAY1_LAST)
    q = make(clock=clock)
    b = q.bucket("peer-a")
    q.charge(b, "turns")
    clock.t = DAY2_START
    q.refund(b, "turns")
    assert q.remaining(b)["turns"] == 3


def test_utc_day() -> None:
    assert utc_day(DAY1_LAST) == (2026, 301)
    assert utc_day(DAY2_START) == (2026, 302)


def test_client_ip_hops() -> None:
    assert client_ip("peer", "a, b", 0) == "peer"
    assert client_ip("peer", "2001:db8:1::5, 2001:db8:2::7", 1) == "2001:db8:2::7"
    assert client_ip("peer", "a, b, c", 2) == "b"
    assert client_ip("peer", "a", 2) == "peer"
    assert client_ip("peer", None, 1) == "peer"
    assert client_ip(None, None, 0) == "unknown"


def test_normalize_ip_ipv6_64() -> None:
    assert normalize_ip("2001:db8:1:1::a") == normalize_ip("2001:db8:1:1::b")
    assert normalize_ip("2001:db8:1:1::a") == "2001:db8:1:1::/64"
    assert normalize_ip("2001:db8:1:2::a") != normalize_ip("2001:db8:1:1::a")
    assert normalize_ip("unknown") == "unknown"


def test_bucket_groups_ipv6_and_hides_ip() -> None:
    q = make()
    a = q.bucket("2001:db8:1:1::a")
    assert a == q.bucket("2001:db8:1:1::b")
    assert len(a) == 16
    assert int(a, 16) >= 0
    assert "2001" not in a and "db8" not in a
    assert q.bucket("2001:db8:1:2::a") != a


def test_bucket_salt_differs_per_instance() -> None:
    assert make().bucket("peer-a") != make().bucket("peer-a")


def _scope(peer: str, xff: str | None = None) -> dict[str, object]:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return {"type": "http", "client": (peer, 1234), "headers": headers}


def test_bucket_for_scope_ignores_spoofed_xff_without_hops() -> None:
    q = make()
    b1 = q.bucket_for_scope(_scope("2001:db8:9::1", "2001:db8:1::5"), 0)
    b2 = q.bucket_for_scope(_scope("2001:db8:9::1", "2001:db8:3::5"), 0)
    assert b1 == b2 == q.bucket("2001:db8:9::1")


def test_bucket_for_scope_rightmost_trusted_hop() -> None:
    q = make()
    b = q.bucket_for_scope(_scope("2001:db8:9::1", "2001:db8:1::5, 2001:db8:2::7"), 1)
    assert b == q.bucket("2001:db8:2::7")
    short = q.bucket_for_scope(_scope("2001:db8:9::1", "2001:db8:1::5"), 2)
    assert short == q.bucket("2001:db8:9::1")


def test_rate_fixed_window() -> None:
    clock = FakeClock(float(60 * 1000))
    q = make(clock=clock, rate=5)
    b = q.bucket("peer-a")
    for _ in range(5):
        q.hit_rate(b)
    with pytest.raises(RateLimited):
        q.hit_rate(b)
    q.hit_rate(q.bucket("peer-b"))
    clock.t += 60
    q.hit_rate(b)


# --- 요청 헬퍼 ---


def _request(app: FastAPI, peer: str = "2001:db8:5::1") -> Request:
    scope = dict(_scope(peer))
    scope["app"] = app
    return Request(scope)  # type: ignore[arg-type]


def test_helpers_noop_when_demo_off() -> None:
    app = FastAPI()
    app.state.demo_quota = None
    req = _request(app)
    assert request_bucket(req) is None
    charge_request(req, "turns", 100)
    refund_request(req, "turns")


def test_helpers_charge_refund_and_errors() -> None:
    app = FastAPI()
    caps: dict[Kind, int] = {**CAPS, "agents": 3}
    q = make(caps=caps)
    app.state.demo_quota = q
    app.state.demo_settings = Settings(_env_file=None)  # type: ignore[call-arg]
    req = _request(app)
    b = request_bucket(req)
    assert b == q.bucket("2001:db8:5::1")

    for _ in range(3):
        charge_request(req, "turns")
    with pytest.raises(HTTPException) as ei:
        charge_request(req, "turns")
    assert ei.value.status_code == 429
    assert ei.value.detail == {
        "code": "demo_quota_exceeded",
        "message": "오늘 데모 사용 한도를 다 썼습니다. 내일 다시 이용해 주세요.",
        "kind": "turns",
        "reset_at": q.reset_at(),
    }
    refund_request(req, "turns")
    assert q.remaining(b)["turns"] == 1

    charge_request(req, "agents")
    charge_request(_request(app, "2001:db8:6::1"), "agents")
    charge_request(_request(app, "2001:db8:7::1"), "agents")
    with pytest.raises(HTTPException) as ei2:
        charge_request(_request(app, "2001:db8:8::1"), "agents")
    assert ei2.value.status_code == 503
    assert ei2.value.detail == {
        "code": "demo_daily_cap",
        "message": "오늘 데모 전체 사용량이 모두 소진되었습니다. 내일 다시 이용해 주세요.",
        "kind": "agents",
        "reset_at": q.reset_at(),
    }
