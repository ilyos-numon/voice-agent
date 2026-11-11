import base64

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.api.schemas import AskRequest, AskResponse, SourceOut, TimingsOut
from app.config import get_settings
from app.pipeline.audio import MAX_AUDIO_BYTES, AudioDecodeError, NoSpeechError, sniff_format
from app.pipeline.runner import Pipeline
from app.pipeline.types import AskResult

VERSION = "0.1.0"

router = APIRouter()


def _to_response(result: AskResult) -> AskResponse:
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


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": VERSION, "pipeline_mode": get_settings().pipeline_mode}


@router.post("/api/ask", response_model=AskResponse)
def ask(body: AskRequest, request: Request) -> AskResponse:
    pipeline: Pipeline = request.app.state.pipeline
    result = pipeline.run(text=body.text)
    return _to_response(result)


@router.post("/api/ask-audio", response_model=AskResponse)
async def ask_audio(request: Request) -> AskResponse:
    body = await request.body()
    if len(body) == 0:
        raise HTTPException(status_code=400, detail="empty audio")
    if len(body) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio too large")
    if sniff_format(body) is None:
        raise HTTPException(status_code=415, detail="unsupported audio format")
    pipeline: Pipeline = request.app.state.pipeline
    try:
        result = await run_in_threadpool(pipeline.run, audio=body)
    except AudioDecodeError as e:
        raise HTTPException(status_code=400, detail="audio decode failed") from e
    except NoSpeechError as e:
        raise HTTPException(status_code=422, detail="no speech recognized") from e
    if result.transcript.strip() == "":
        raise HTTPException(status_code=422, detail="no speech recognized")
    return _to_response(result)
