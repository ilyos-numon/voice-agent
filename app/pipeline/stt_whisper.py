from typing import Any

from app.pipeline.audio import MIN_AUDIO_SAMPLES, SILENCE_RMS, NoSpeechError, decode_audio, rms

INSTALL_HINT = "STT_BACKEND=whisper requires: uv sync --extra dev --extra tts --extra stt"
INITIAL_PROMPT = "주민등록등본, 가족관계증명서, 인감증명서, 무인발급기, 수수료, 신분증."


class WhisperSTT:
    def __init__(
        self, model: str = "small", beam_size: int = 1, compute_type: str = "int8", warm_up: bool = True
    ) -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise RuntimeError(INSTALL_HINT) from e
        self.beam_size = beam_size
        self._model: Any = WhisperModel(model, device="cpu", compute_type=compute_type)
        if warm_up:
            import numpy as np

            segments, _info = self._model.transcribe(
                np.zeros(16000, dtype=np.float32), language="ko", beam_size=self.beam_size
            )
            for _ in segments:
                pass

    def transcribe(self, audio: bytes | None, text_hint: str | None) -> str:
        if audio is None:
            return text_hint or ""
        pcm = decode_audio(audio)
        if len(pcm) < MIN_AUDIO_SAMPLES or rms(pcm) < SILENCE_RMS:
            raise NoSpeechError("no speech recognized")
        segments, _info = self._model.transcribe(
            pcm,
            language="ko",
            beam_size=self.beam_size,
            initial_prompt=INITIAL_PROMPT,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        if not text:
            raise NoSpeechError("no speech recognized")
        return text
