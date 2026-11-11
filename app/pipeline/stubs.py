import io
import json
import wave
from pathlib import Path

from app.pipeline.types import FaqItem

FALLBACK_ANSWER = "해당 안내를 찾지 못했습니다. 창구 직원에게 문의해 주세요."


def load_faq(path: Path) -> list[FaqItem]:
    with open(path, encoding="utf-8") as f:
        return [FaqItem(**row) for row in json.load(f)]


def _tokens(text: str) -> set[str]:
    return {t.strip("?.!,") for t in text.split()} - {""}


class PassthroughSTT:
    def transcribe(self, audio: bytes | None, text_hint: str | None) -> str:
        return text_hint or ""


class KeywordRetriever:
    def __init__(self, faq_path: Path) -> None:
        self.items = load_faq(faq_path)

    def search(self, query: str, top_k: int = 3) -> list[FaqItem]:
        q = _tokens(query)
        scored = [(len(q & _tokens(it.question)), it) for it in self.items]
        hits = sorted((s for s in scored if s[0] > 0), key=lambda s: -s[0])
        return [it for _, it in hits[:top_k]]


class TemplateLLM:
    def answer(self, query: str, context: list[FaqItem]) -> str:
        return context[0].answer if context else FALLBACK_ANSWER


class SilentTTS:
    def synthesize(self, text: str) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 1600)  # 100ms
        return buf.getvalue()
