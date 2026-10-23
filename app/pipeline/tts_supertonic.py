from collections.abc import Callable
from typing import Any

from app.pipeline.sentences import split_sentences
from app.pipeline.wav import pcm16_to_wav

INSTALL_HINT = "TTS_BACKEND=supertonic requires: uv sync --extra dev --extra tts"

# supertonic은 마침표 기준으로만 내부 분할하고, 한 조각의 text ids가 ~1000을 넘으면
# onnxruntime이 "broadcast ... 1000 by N"으로 실패한다 (한글 1자 ≈ 2 ids, 실측 508자=998 ids OK,
# 512자=1005 ids 실패). 1자 최대 3 ids(초·중·종성)로 잡아도 1000 미만이 되도록 300자로 자른다.
MAX_SINGLE_PASS_CHARS = 300


def sanitize_tts_text(text: str, is_supported: Callable[[str], bool]) -> str:
    """Replace characters the TTS cannot speak with spaces and collapse whitespace."""
    verdict = {ch: is_supported(ch) for ch in set(text)}
    cleaned = "".join(ch if verdict[ch] else " " for ch in text)
    return " ".join(cleaned.split())


def chunk_tts_text(text: str, max_chars: int = MAX_SINGLE_PASS_CHARS) -> list[str]:
    """max_chars 이하면 그대로 한 조각, 넘으면 문장 단위로 나누고 그래도 긴 조각은 강제로 자른다."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    for piece in split_sentences(text):
        chunks.extend(piece[i : i + max_chars] for i in range(0, len(piece), max_chars))
    return chunks


class SupertonicTTS:
    sample_rate: int

    def __init__(
        self, voice: str = "F1", lang: str = "ko", total_steps: int = 8, warm_up: bool = True
    ) -> None:
        try:
            from supertonic import TTS
        except ImportError as e:
            raise RuntimeError(INSTALL_HINT) from e
        self.lang = lang
        self.total_steps = total_steps
        self._tts: Any = TTS(auto_download=True)
        self._style: Any = self._tts.get_voice_style(voice_name=voice)
        self.sample_rate = int(self._tts.sample_rate)
        if warm_up:
            self.synthesize("안녕하세요")

    def _is_supported(self, ch: str) -> bool:
        is_valid, _unsupported = self._tts.model.text_processor.validate_text(ch)
        return bool(is_valid)

    def synthesize(self, text: str) -> bytes:
        import numpy as np

        text = sanitize_tts_text(text, self._is_supported)
        if not text.strip():
            silence = np.zeros(self.sample_rate // 10, dtype="<i2")
            return pcm16_to_wav(silence.tobytes(), self.sample_rate, 1)
        parts = []
        for chunk in chunk_tts_text(text):
            wav, _duration = self._tts.synthesize(
                chunk,
                voice_style=self._style,
                lang=self.lang,
                total_steps=self.total_steps,
                verbose=False,
            )
            part = np.asarray(wav, dtype=np.float32)
            if part.ndim == 2:
                part = part[0]
            parts.append(part)
        samples = parts[0] if len(parts) == 1 else np.concatenate(parts)
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
        return pcm16_to_wav(pcm.tobytes(), self.sample_rate, 1)
