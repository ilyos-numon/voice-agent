"""GET /api/demo: 데모 안내·방문자 한도 잔량·요청 토큰 (전역 상태는 넣지 않는다)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.demo.guard import TokenSigner
from app.demo.quota import DemoQuota, request_bucket

NOTICE = "데모 버전입니다. 기능과 사용량이 제한됩니다. 완성된 기술이 필요하면 개발자에게 문의해 주세요."
PRIVACY_NOTICE = "질문 문장은 답 요약을 위해 외부 AI API로 전송됩니다(음성은 전송하지 않습니다)."

demo_router = APIRouter()


class DemoOut(BaseModel):
    demo_mode: bool
    contact: str | None
    notice: str
    privacy_notice: str
    limits: dict[str, int] | None
    remaining: dict[str, int] | None
    reset_at: str | None
    bucket: str | None
    token: str | None
    token_expires_in: int | None


@demo_router.get("/api/demo", response_model=DemoOut)
def demo_info(request: Request) -> DemoOut:
    state = request.app.state
    settings = getattr(state, "demo_settings", None)
    contact = str(getattr(settings, "demo_contact", "") or "") or None
    quota = getattr(state, "demo_quota", None)
    bucket = request_bucket(request) if isinstance(quota, DemoQuota) else None
    if not isinstance(quota, DemoQuota) or bucket is None:
        return DemoOut(
            demo_mode=False,
            contact=contact,
            notice=NOTICE,
            privacy_notice=PRIVACY_NOTICE,
            limits=None,
            remaining=None,
            reset_at=None,
            bucket=None,
            token=None,
            token_expires_in=None,
        )
    signer = getattr(state, "demo_signer", None)
    signer = signer if isinstance(signer, TokenSigner) else None
    return DemoOut(
        demo_mode=True,
        contact=contact,
        notice=NOTICE,
        privacy_notice=PRIVACY_NOTICE,
        limits={str(k): v for k, v in quota.limits.items()},
        remaining={str(k): v for k, v in quota.remaining(bucket).items()},
        reset_at=quota.reset_at(),
        bucket=bucket,
        token=signer.issue(bucket) if signer is not None else None,
        token_expires_in=signer.ttl_s if signer is not None else None,
    )
