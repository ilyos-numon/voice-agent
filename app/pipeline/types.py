from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FaqItem:
    id: str  # "faq-001" 형식
    question: str
    answer: str
    source: str  # 예: "합성 FAQ 샘플 (data/faq/sample_faq.json)"


@dataclass
class AskResult:
    transcript: str
    answer: str
    source: FaqItem | None
    timings: dict[str, float]  # 키 고정: "stt_ms","retrieve_ms","llm_ms","tts_ms","total_ms"
    audio_wav: bytes


class STT(Protocol):
    def transcribe(self, audio: bytes | None, text_hint: str | None) -> str: ...


class Retriever(Protocol):
    def search(self, query: str, top_k: int = 3) -> list[FaqItem]: ...


class LLM(Protocol):
    def answer(self, query: str, context: list[FaqItem]) -> str: ...


class SentenceStreamingLLM(LLM, Protocol):
    def stream_sentences(self, query: str, context: list[FaqItem]) -> Iterator[str]: ...


class TTS(Protocol):
    def synthesize(self, text: str) -> bytes: ...  # WAV 바이트
