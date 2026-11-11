import time
from collections.abc import Iterator
from pathlib import Path

from app.config import Settings
from app.pipeline.runner import build_pipeline
from app.pipeline.stream import AudioEvent, DoneEvent, MetaEvent, iter_ask
from app.pipeline.types import FaqItem

FAQ_PATH = Path(__file__).resolve().parents[2] / "data" / "faq" / "sample_faq.json"
DONE_KEYS = {"stt_ms", "retrieve_ms", "llm_ms", "tts_ms", "first_audio_ms", "total_ms"}
Q = "주민등록등본 떼려면 뭐 필요해요?"
S1 = "첫 번째 문장입니다."
S2 = "두 번째 문장입니다."


class SlowStreamLLM:
    def answer(self, query: str, context: list[FaqItem]) -> str:
        return " ".join(self.stream_sentences(query, context))

    def stream_sentences(self, query: str, context: list[FaqItem]) -> Iterator[str]:
        yield S1
        time.sleep(0.3)
        yield S2


class SlowTTS:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text: str) -> bytes:
        self.calls.append(text)
        time.sleep(0.2)
        return b"RIFF" + b"\x00" * 40


def _events() -> list[object]:
    p = build_pipeline(Settings(pipeline_mode="stub", faq_path=FAQ_PATH))
    p.llm = SlowStreamLLM()
    p.tts = SlowTTS()
    return list(iter_ask(p, text=Q))


def test_first_audio_overlaps_llm() -> None:
    ev = _events()
    done = ev[-1]
    assert isinstance(done, DoneEvent)
    t = done.timings
    assert t["llm_ms"] >= 300
    assert t["first_audio_ms"] < t["llm_ms"] + 200 - 100


def test_event_order_and_keys() -> None:
    ev = _events()
    meta = ev[0]
    assert isinstance(meta, MetaEvent)
    assert set(meta.timings) == {"stt_ms", "retrieve_ms", "llm_ms"}
    assert meta.answer == f"{S1} {S2}"
    assert meta.sentence_count == 2
    audios = ev[1:-1]
    assert all(isinstance(a, AudioEvent) for a in audios)
    assert [(a.index, a.text) for a in audios if isinstance(a, AudioEvent)] == [(0, S1), (1, S2)]
    done = ev[-1]
    assert isinstance(done, DoneEvent)
    assert done.sentence_count == 2
    assert set(done.timings) == DONE_KEYS
