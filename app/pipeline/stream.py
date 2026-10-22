"""문장 단위로 TTS 이벤트를 내보내는 스트림 파이프라인 (Pipeline은 import만)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass

from app.pipeline.audio import NoSpeechError
from app.pipeline.runner import Pipeline
from app.pipeline.sentences import split_sentences
from app.pipeline.types import FaqItem


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


@dataclass(frozen=True)
class MetaEvent:
    transcript: str
    answer: str
    source: FaqItem | None
    sentence_count: int
    timings: dict[str, float]  # 키: stt_ms, retrieve_ms, llm_ms


@dataclass(frozen=True)
class AudioEvent:
    index: int
    text: str
    audio_wav: bytes  # 완전한 WAV (RIFF). API 층이 base64로 바꾼다
    tts_ms: float
    elapsed_ms: float


@dataclass(frozen=True)
class DoneEvent:
    sentence_count: int
    timings: dict[str, float]  # 키 고정: stt_ms, retrieve_ms, llm_ms, tts_ms, first_audio_ms, total_ms


StreamEvent = MetaEvent | AudioEvent | DoneEvent


def iter_ask(
    pipeline: Pipeline, text: str | None = None, audio: bytes | None = None
) -> Iterator[StreamEvent]:
    t0 = time.perf_counter()
    t = time.perf_counter()
    transcript = pipeline.stt.transcribe(audio, text)
    stt_ms = _ms(t)
    if not transcript.strip():
        raise NoSpeechError("no speech detected")
    t = time.perf_counter()
    context = pipeline.retriever.search(transcript)
    retrieve_ms = _ms(t)
    t = time.perf_counter()
    answer = pipeline.llm.answer(transcript, context)
    llm_ms = _ms(t)
    sentences = split_sentences(answer) or [answer]
    source = context[0] if context else None
    base = {"stt_ms": stt_ms, "retrieve_ms": retrieve_ms, "llm_ms": llm_ms}
    yield MetaEvent(transcript, answer, source, len(sentences), dict(base))

    tts_total = 0.0
    first_audio_ms = 0.0
    for i, sentence in enumerate(sentences):
        t = time.perf_counter()
        wav = pipeline.tts.synthesize(sentence)
        tts_ms = _ms(t)
        tts_total += tts_ms
        elapsed = _ms(t0)
        if i == 0:
            first_audio_ms = elapsed
        yield AudioEvent(i, sentence, wav, tts_ms, elapsed)

    timings = {**base, "tts_ms": round(tts_total, 3), "first_audio_ms": first_audio_ms,
               "total_ms": _ms(t0)}
    yield DoneEvent(len(sentences), timings)
