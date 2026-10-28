"""데모 모드 설치: /api/demo 라우터, 미들웨어, app.state 의 한도·토큰·차단 객체."""

from __future__ import annotations

from fastapi import FastAPI

from app.config import Settings
from app.demo.guard import AbuseTracker, TokenSigner, parse_steps
from app.demo.quota import DemoQuota
from app.demo.routes import demo_router
from app.demo.security import (
    BodyLimitMiddleware,
    BotGuardMiddleware,
    ExposureGuardMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)


def install_demo(app: FastAPI, settings: Settings) -> None:
    app.include_router(demo_router)
    app.state.demo_settings = settings
    hops = settings.demo_trusted_proxy_hops
    if settings.demo_mode:
        app.state.demo_quota = DemoQuota(
            limits={
                "turns": settings.demo_daily_turns,
                "audio_seconds": settings.demo_daily_audio_seconds,
                "agents": settings.demo_daily_agents,
                "scorecards": settings.demo_daily_scorecards,
            },
            global_caps={
                "turns": settings.demo_global_daily_turns,
                "audio_seconds": settings.demo_global_daily_audio_seconds,
                "agents": settings.demo_global_daily_agents,
                "scorecards": settings.demo_global_daily_scorecards,
            },
            rate_per_minute=settings.demo_rate_per_minute,
        )
        if settings.demo_bot_guard:
            app.state.demo_signer = TokenSigner(settings.demo_token_secret, settings.demo_token_ttl_s)
            app.state.demo_abuse = AbuseTracker(
                settings.demo_abuse_threshold,
                settings.demo_abuse_window_s,
                parse_steps(settings.demo_block_steps),
            )
        else:
            app.state.demo_signer = None
            app.state.demo_abuse = None
        # add_middleware 는 마지막에 넣은 것이 가장 바깥이다.
        # 실행 순서(바깥→안): SecurityHeaders → ExposureGuard → BotGuard → RateLimit → BodyLimit
        app.add_middleware(
            BodyLimitMiddleware,
            max_json_bytes=settings.demo_max_json_bytes,
            max_audio_bytes=settings.demo_max_audio_bytes,
        )
        app.add_middleware(RateLimitMiddleware, trusted_hops=hops)
        app.add_middleware(BotGuardMiddleware, trusted_hops=hops)
        app.add_middleware(ExposureGuardMiddleware)
    else:
        app.state.demo_quota = None
        app.state.demo_signer = None
        app.state.demo_abuse = None
    app.add_middleware(
        SecurityHeadersMiddleware,
        frame_ancestors=settings.demo_frame_ancestors,
        trusted_hops=hops,
        csp=settings.demo_mode,
    )
