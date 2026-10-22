from typing import Any

from app.pipeline.wav import pcm16_to_wav

INSTALL_HINT = "TTS_BACKEND=supertonic requires: uv sync --extra dev --extra tts"


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

    def synthesize(self, text: str) -> bytes:
        import numpy as np

        if not text.strip():
            silence = np.zeros(self.sample_rate // 10, dtype="<i2")
            return pcm16_to_wav(silence.tobytes(), self.sample_rate, 1)
        wav, _duration = self._tts.synthesize(
            text,
            voice_style=self._style,
            lang=self.lang,
            total_steps=self.total_steps,
            verbose=False,
        )
        samples = np.asarray(wav, dtype=np.float32)
        if samples.ndim == 2:
            samples = samples[0]
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
        return pcm16_to_wav(pcm.tobytes(), self.sample_rate, 1)
