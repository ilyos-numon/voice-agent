import base64

from fastapi import APIRouter, Request

from app.api.schemas import AskRequest, AskResponse, SourceOut, TimingsOut
from app.config import get_settings
from app.pipeline.runner import Pipeline

VERSION = "0.1.0"

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": VERSION, "pipeline_mode": get_settings().pipeline_mode}


@router.post("/api/ask", response_model=AskResponse)
def ask(body: AskRequest, request: Request) -> AskResponse:
    pipeline: Pipeline = request.app.state.pipeline
    result = pipeline.run(text=body.text)
    source = (
        SourceOut(id=result.source.id, question=result.source.question, source=result.source.source)
        if result.source is not None
        else None
    )
    return AskResponse(
        transcript=result.transcript,
        answer=result.answer,
        source=source,
        timings=TimingsOut(**result.timings),
        audio_wav_b64=base64.b64encode(result.audio_wav).decode("ascii"),
    )
