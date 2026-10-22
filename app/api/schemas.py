from pydantic import BaseModel, Field, field_validator


class AskRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("text must not be blank")
        return stripped


class SourceOut(BaseModel):
    id: str
    question: str
    source: str


class TimingsOut(BaseModel):
    stt_ms: float
    retrieve_ms: float
    llm_ms: float
    tts_ms: float
    total_ms: float


class AskResponse(BaseModel):
    transcript: str
    answer: str
    source: SourceOut | None
    timings: TimingsOut
    audio_wav_b64: str


class StreamMetaOut(BaseModel):
    transcript: str
    answer: str
    source: SourceOut | None
    sentence_count: int
    timings: dict[str, float]


class StreamAudioOut(BaseModel):
    index: int
    text: str
    audio_wav_b64: str
    tts_ms: float
    elapsed_ms: float


class StreamTimingsOut(TimingsOut):
    first_audio_ms: float


class StreamDoneOut(BaseModel):
    sentence_count: int
    timings: StreamTimingsOut


class StreamErrorOut(BaseModel):
    detail: str
