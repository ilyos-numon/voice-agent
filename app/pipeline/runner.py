import time

from app.config import Settings
from app.pipeline.stubs import KeywordRetriever, PassthroughSTT, SilentTTS, TemplateLLM
from app.pipeline.tts_supertonic import SupertonicTTS
from app.pipeline.types import LLM, STT, TTS, AskResult, Retriever


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


class Pipeline:
    def __init__(self, stt: STT, retriever: Retriever, llm: LLM, tts: TTS) -> None:
        self.stt, self.retriever, self.llm, self.tts = stt, retriever, llm, tts

    def run(self, text: str | None = None, audio: bytes | None = None) -> AskResult:
        t0 = time.perf_counter()
        t = time.perf_counter()
        transcript = self.stt.transcribe(audio, text)
        stt_ms = _ms(t)
        t = time.perf_counter()
        context = self.retriever.search(transcript)
        retrieve_ms = _ms(t)
        t = time.perf_counter()
        answer = self.llm.answer(transcript, context)
        llm_ms = _ms(t)
        t = time.perf_counter()
        audio_wav = self.tts.synthesize(answer)
        tts_ms = _ms(t)
        timings = {"stt_ms": stt_ms, "retrieve_ms": retrieve_ms, "llm_ms": llm_ms,
                   "tts_ms": tts_ms, "total_ms": _ms(t0)}
        source = context[0] if context else None
        return AskResult(transcript, answer, source, timings, audio_wav)


def build_tts(settings: Settings) -> TTS:
    backend = settings.tts_backend
    if backend == "stub":
        return SilentTTS()
    if backend == "supertonic":
        return SupertonicTTS(voice=settings.tts_voice)
    raise ValueError(f"unknown TTS_BACKEND: {backend}")


def build_pipeline(settings: Settings) -> Pipeline:
    mode = settings.pipeline_mode
    if mode != "stub":
        raise ValueError(f"unknown PIPELINE_MODE: {mode}")
    return Pipeline(PassthroughSTT(), KeywordRetriever(settings.faq_path), TemplateLLM(), build_tts(settings))
