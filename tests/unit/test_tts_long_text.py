import io
import wave
from typing import Any

import numpy as np

from app.pipeline.tts_supertonic import MAX_SINGLE_PASS_CHARS, SupertonicTTS, chunk_tts_text

SR = 24000


def _long_text_without_periods(n: int) -> str:
    # supertonic은 마침표에서만 내부 분할 → 마침표 없는 긴 구간이 한계를 넘는다 (faq-416 형태)
    words: list[str] = []
    while len(" ".join(words)) < n:
        words.append("치매치료관리비")
    return " ".join(words)


def test_short_text_is_single_chunk() -> None:
    assert chunk_tts_text("안녕하세요. 반갑습니다") == ["안녕하세요. 반갑습니다"]


def test_long_text_chunks_within_limit_and_keep_words() -> None:
    text = _long_text_without_periods(1100)
    chunks = chunk_tts_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= MAX_SINGLE_PASS_CHARS for c in chunks)
    assert " ".join(chunks).split() == text.split()


def test_long_text_without_spaces_is_hard_split() -> None:
    text = "가" * (MAX_SINGLE_PASS_CHARS * 2 + 7)
    chunks = chunk_tts_text(text)
    assert all(len(c) <= MAX_SINGLE_PASS_CHARS for c in chunks)
    assert "".join(chunks) == text


class _FakeModel:
    """한계를 넘는 입력이면 onnxruntime처럼 실패하는 가짜 supertonic."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.calls: list[str] = []

    def synthesize(self, text: str, **_: Any) -> tuple[Any, Any]:
        if len(text) > self.limit:
            raise RuntimeError("Attempting to broadcast an axis ... 1000 by 1356")
        self.calls.append(text)
        return np.full((1, len(text) * 10), 0.5, dtype=np.float32), [len(text) / 100]


def _fake_tts(limit: int) -> tuple[SupertonicTTS, _FakeModel]:
    tts = object.__new__(SupertonicTTS)
    model = _FakeModel(limit)
    tts._tts = model
    tts._style = None
    tts.lang = "ko"
    tts.total_steps = 8
    tts.sample_rate = SR
    tts._is_supported = lambda ch: True  # type: ignore[method-assign]
    return tts, model


def _read(wav_bytes: bytes) -> tuple[int, int, int, int]:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()


def test_long_text_synthesized_in_chunks_into_one_wav() -> None:
    tts, model = _fake_tts(limit=MAX_SINGLE_PASS_CHARS)
    text = _long_text_without_periods(1100)
    wav_bytes = tts.synthesize(text)
    assert len(model.calls) > 1
    rate, ch, width, frames = _read(wav_bytes)
    assert (rate, ch, width) == (SR, 1, 2)
    assert frames == sum(len(c) * 10 for c in model.calls)


def test_short_text_uses_single_call() -> None:
    tts, model = _fake_tts(limit=MAX_SINGLE_PASS_CHARS)
    wav_bytes = tts.synthesize("안녕하세요. 반갑습니다")
    assert model.calls == ["안녕하세요. 반갑습니다"]
    assert _read(wav_bytes)[3] == len("안녕하세요. 반갑습니다") * 10
