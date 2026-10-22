import time

from app.config import Settings
from app.pipeline.bm25 import BM25Retriever
from app.pipeline.llm_qwen import QwenLLM
from app.pipeline.stt_whisper import WhisperSTT
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


def build_stt(settings: Settings) -> STT:
    backend = settings.stt_backend
    if backend == "stub":
        return PassthroughSTT()
    if backend == "whisper":
        return WhisperSTT(model=settings.stt_model, beam_size=settings.stt_beam_size)
    raise ValueError(f"unknown STT_BACKEND: {backend}")


def build_tts(settings: Settings) -> TTS:
    backend = settings.tts_backend
    if backend == "stub":
        return SilentTTS()
    if backend == "supertonic":
        return SupertonicTTS(voice=settings.tts_voice)
    raise ValueError(f"unknown TTS_BACKEND: {backend}")


def build_retriever(settings: Settings) -> Retriever:
    backend = settings.retriever_backend
    if backend == "keyword":
        return KeywordRetriever(settings.faq_path)
    if backend == "bm25":
        return BM25Retriever.from_path(settings.faq_path)
    raise ValueError(f"unknown RETRIEVER_BACKEND: {backend}")


def build_llm(settings: Settings) -> LLM:
    backend = settings.llm_backend
    if backend == "stub":
        return TemplateLLM()
    if backend == "qwen":
        if not settings.llm_api_key:
            return TemplateLLM()
        return QwenLLM(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_s=settings.llm_timeout_s,
        )
    raise ValueError(f"unknown LLM_BACKEND: {backend}")


def build_pipeline(settings: Settings) -> Pipeline:
    mode = settings.pipeline_mode
    if mode != "stub":
        raise ValueError(f"unknown PIPELINE_MODE: {mode}")
    return Pipeline(build_stt(settings), build_retriever(settings), build_llm(settings), build_tts(settings))
