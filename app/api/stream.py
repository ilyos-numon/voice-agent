"""문장 단위 TTS를 SSE(text/event-stream)로 내보내는 라우터."""

import base64
import logging
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.schemas import (
    AskRequest,
    SourceOut,
    StreamAudioOut,
    StreamDoneOut,
    StreamErrorOut,
    StreamMetaOut,
    StreamTimingsOut,
)
from app.pipeline.audio import MAX_AUDIO_BYTES, AudioDecodeError, NoSpeechError, sniff_format
from app.pipeline.runner import Pipeline
from app.pipeline.stream import AudioEvent, DoneEvent, MetaEvent, iter_ask

logger = logging.getLogger(__name__)

stream_router = APIRouter()

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def format_sse(event: str, data: BaseModel) -> bytes:
    return f"event: {event}\ndata: {data.model_dump_json()}\n\n".encode()


def _r(timings: dict[str, float]) -> dict[str, float]:
    return {k: round(v, 1) for k, v in timings.items()}


def _sse_events(pipeline: Pipeline, text: str | None = None, audio: bytes | None = None) -> Iterator[bytes]:
    try:
        for ev in iter_ask(pipeline, text=text, audio=audio):
            if isinstance(ev, MetaEvent):
                source = (
                    SourceOut(id=ev.source.id, question=ev.source.question, source=ev.source.source)
                    if ev.source is not None
                    else None
                )
                yield format_sse(
                    "meta",
                    StreamMetaOut(
                        transcript=ev.transcript,
                        answer=ev.answer,
                        source=source,
                        sentence_count=ev.sentence_count,
                        timings=_r(ev.timings),
                    ),
                )
            elif isinstance(ev, AudioEvent):
                yield format_sse(
                    "audio",
                    StreamAudioOut(
                        index=ev.index,
                        text=ev.text,
                        audio_wav_b64=base64.b64encode(ev.audio_wav).decode("ascii"),
                        tts_ms=round(ev.tts_ms, 1),
                        elapsed_ms=round(ev.elapsed_ms, 1),
                    ),
                )
            elif isinstance(ev, DoneEvent):
                yield format_sse(
                    "done",
                    StreamDoneOut(
                        sentence_count=ev.sentence_count,
                        timings=StreamTimingsOut(**_r(ev.timings)),
                    ),
                )
    except AudioDecodeError:
        yield format_sse("error", StreamErrorOut(detail="audio decode failed"))
    except NoSpeechError:
        yield format_sse("error", StreamErrorOut(detail="no speech recognized"))
    except Exception:
        logger.exception("ask stream failed")
        yield format_sse("error", StreamErrorOut(detail="internal error"))


def _stream(gen: Iterator[bytes]) -> StreamingResponse:
    return StreamingResponse(gen, media_type="text/event-stream", headers=SSE_HEADERS)


@stream_router.post("/api/ask-stream")
def ask_stream(body: AskRequest, request: Request) -> StreamingResponse:
    pipeline: Pipeline = request.app.state.pipeline
    return _stream(_sse_events(pipeline, text=body.text))


@stream_router.post("/api/ask-audio-stream")
async def ask_audio_stream(request: Request) -> StreamingResponse:
    body = await request.body()
    if len(body) == 0:
        raise HTTPException(status_code=400, detail="empty audio")
    if len(body) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio too large")
    if sniff_format(body) is None:
        raise HTTPException(status_code=415, detail="unsupported audio format")
    pipeline: Pipeline = request.app.state.pipeline
    return _stream(_sse_events(pipeline, audio=body))
